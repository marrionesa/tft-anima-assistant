#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ST7735.h>
#include <SPI.h>
#include <pgmspace.h>

#include "secrets.h"
#include "anima_screens.h"           // 10 pantallas de estado 160x128 (PROGMEM)
#include "anima_splash_160x128.h"    // splash de arranque
#include "idle_anim.h"               // respiro del rostro en RLE (el "gif")

// =====================================================
// TFT: cableado confirmado para NodeMCU ESP8266
// =====================================================
#define TFT_CS  D1
#define TFT_DC  D2
#define TFT_RST D0
#define SCREEN_W 160
#define SCREEN_H 128

Adafruit_ST7735 tft(TFT_CS, TFT_DC, TFT_RST);
WebSocketsClient webSocket;

// =====================================================
// Estados visuales de ANIMA
// =====================================================
enum AnimaState : uint8_t {
  STATE_BOOT,
  STATE_READY,
  STATE_LISTENING,
  STATE_THINKING,
  STATE_RESPONDING,
  STATE_COMPLETE,
  STATE_OFFLINE,
  STATE_ERROR,
  STATE_UPDATING,
  STATE_MUTED
};

AnimaState currentState = STATE_BOOT;
bool wsConnected = false;

unsigned long lastPing = 0;
unsigned long lastTextTick = 0;

// =====================================================
// Reposo en dos fases
//   1) 10 s tras la última actividad → pantalla REPOSO (estática)
//   2) 25 s tras la última actividad → respiro animado (idle_anim.h)
// Cualquier evento del WebSocket devuelve a la pantalla de estado.
// =====================================================
static const unsigned long IDLE_READY_MS = 10000UL;
static const unsigned long IDLE_SLEEP_MS = 25000UL;

unsigned long lastInteractionAt = 0;
bool idleTimerActive = false;
bool sleepActive = false;        // respiro animado en curso
uint8_t sleepFrame = 0;
unsigned long sleepNextMs = 0;

void armIdleTimer() {
  lastInteractionAt = millis();
  idleTimerActive = true;
}

void cancelIdleTimer() {
  idleTimerActive = false;
}

// =====================================================
// Transición de respuesta y texto animado
// =====================================================
enum ResponseStage : uint8_t {
  RESPONSE_NONE,
  RESPONSE_SHOWING_WAVE,
  RESPONSE_SHOWING_COMPLETE,
  RESPONSE_TYPING
};

ResponseStage responseStage = RESPONSE_NONE;
unsigned long responseDeadline = 0;

static const uint8_t MAX_RESPONSE_LINES = 48;
static const uint8_t VISIBLE_RESPONSE_LINES = 7;
String responseLines[MAX_RESPONSE_LINES];
uint8_t responseLineCount = 0;
uint8_t visibleStartLine = 0;
uint8_t typingLine = 0;
uint8_t typingColumn = 0;
bool responseTyping = false;

// =====================================================
// Imagen asociada a cada estado
// =====================================================
const uint16_t* bitmapForState(AnimaState state) {
  switch (state) {
    case STATE_BOOT:       return IMG_INICIANDO;
    case STATE_READY:      return IMG_REPOSO;
    case STATE_LISTENING:  return IMG_TE_ESCUCHO;
    case STATE_THINKING:   return IMG_PENSANDO;
    case STATE_RESPONDING: return IMG_RESPONDIENDO;
    case STATE_COMPLETE:   return IMG_COMPLETADO;
    case STATE_OFFLINE:    return IMG_DESCONECTADA;
    case STATE_ERROR:      return IMG_ERROR;
    case STATE_UPDATING:   return IMG_ACTUALIZANDO;
    case STATE_MUTED:      return IMG_MUTEADA;
    default:               return IMG_REPOSO;
  }
}

// =====================================================
// Render de pantalla completa (una sola pasada SPI)
// =====================================================
void drawState(AnimaState state) {
  currentState = state;

  responseStage = RESPONSE_NONE;
  responseTyping = false;

  tft.drawRGBBitmap(0, 0, bitmapForState(state), SCREEN_W, SCREEN_H);
}

// =====================================================
// Respiro animado: los cuadros viven en flash (PROGMEM)
// comprimidos en RLE; se pintan por filas sin construir el
// frame completo en RAM. No bloquea el WebSocket.
// =====================================================
void sleepDrawFrame(uint8_t idx) {
  uint8_t run;
  uint16_t color;
  uint32_t pos = 0;
  const uint8_t* data = (const uint8_t*)pgm_read_dword(&idleFrames[idx]);
  const uint16_t len = pgm_read_word(&idleFrameLen[idx]);

  for (int y = 0; y < IDLE_H; y++) {
    int x = 0;
    while (x < IDLE_W && pos + 2 < len) {
      run   = pgm_read_byte(&data[pos++]);
      color = pgm_read_byte(&data[pos++]);
      color |= pgm_read_byte(&data[pos++]) << 8;
      tft.drawFastHLine(x, y, run, color);
      x += run;
    }
  }
}

void sleepStart() {
  if (sleepActive) return;
  sleepActive = true;
  sleepFrame = 0;
  sleepNextMs = 0;               // primer cuadro inmediato
}

void sleepStop() {
  sleepActive = false;
}

void sleepTick() {
  if (!sleepActive) return;
  unsigned long now = millis();
  if (sleepNextMs && now - sleepNextMs < IDLE_FRAME_MS) return;
  sleepNextMs = now;
  sleepDrawFrame(sleepFrame);
  sleepFrame = (sleepFrame + 1) % IDLE_FRAMES;
}

// =====================================================
// Preparar texto para que el font básico de la TFT
// pueda mostrar acentos españoles sin glifos UTF-8.
// =====================================================
void normalizeSpanish(String& text) {
  text.replace("á", "a"); text.replace("é", "e");
  text.replace("í", "i"); text.replace("ó", "o");
  text.replace("ú", "u"); text.replace("ü", "u");
  text.replace("ñ", "n");
  text.replace("Á", "A"); text.replace("É", "E");
  text.replace("Í", "I"); text.replace("Ó", "O");
  text.replace("Ú", "U"); text.replace("Ü", "U");
  text.replace("Ñ", "N");
  text.replace("¿", ""); text.replace("¡", "");
  text.replace("«", "\""); text.replace("»", "\"");
  text.replace("–", "-"); text.replace("—", "-");

  // Cualquier byte fuera del ASCII imprimible (emojis, comillas tipográficas,
  // símbolos) se sustituye por '?': el font de la TFT no tiene esos glifos y
  // imprimirlos crudo rompe la línea.
  for (unsigned int i = 0; i < text.length(); ++i) {
    const unsigned char c = (unsigned char)text[i];
    if (c < 32 || c > 126) text.setCharAt(i, '?');
  }
}

// =====================================================
// Separar respuesta en líneas de 23 caracteres
// =====================================================
void prepareResponse(String text) {
  responseLineCount = 0;
  text.replace("\r", " ");
  text.replace("\n", " ");
  normalizeSpanish(text);
  text.trim();

  const uint8_t charsPerLine = 23;

  while (text.length() > 0 && responseLineCount < MAX_RESPONSE_LINES) {
    int cut = min((int)text.length(), (int)charsPerLine);

    if (cut < (int)text.length()) {
      int space = text.lastIndexOf(' ', cut);
      if (space > 0) cut = space;
    }

    String line = text.substring(0, cut);
    line.trim();
    responseLines[responseLineCount++] = line;

    text = text.substring(cut);
    text.trim();
  }

  visibleStartLine = (responseLineCount > VISIBLE_RESPONSE_LINES)
    ? responseLineCount - VISIBLE_RESPONSE_LINES
    : 0;

  typingLine = visibleStartLine;
  typingColumn = 0;
}

// =====================================================
// Pantalla de respuesta con efecto de escritura
// =====================================================
void drawResponseLayout() {
  // REPOSO como fondo de identidad y el centro reservado para el texto.
  tft.drawRGBBitmap(0, 0, IMG_REPOSO, SCREEN_W, SCREEN_H);

  tft.fillRoundRect(5, 22, 150, 88, 4, 0x0000);
  tft.drawRoundRect(5, 22, 150, 88, 4, 0x05D5);

  tft.setTextSize(1);
  tft.setTextColor(0x5FDF);
  tft.setCursor(10, 27);
  tft.print("ANIMA / RESPUESTA");
  tft.drawFastHLine(10, 36, 140, 0x2D6B);

  tft.fillRect(0, 112, SCREEN_W, 16, 0x0000);
  tft.drawFastHLine(8, 113, 144, 0x05D5);
  tft.setTextColor(0x5FDF);
  tft.setCursor(52, 118);
  tft.print("ESCRIBEME");
}

void beginResponseTyping() {
  drawResponseLayout();
  responseStage = RESPONSE_TYPING;
  responseTyping = true;
  lastTextTick = 0;
  typingLine = visibleStartLine;
  typingColumn = 0;
}

void animateResponseText() {
  if (!responseTyping) return;

  const unsigned long now = millis();
  if (now - lastTextTick < 24) return;
  lastTextTick = now;

  while (typingLine < responseLineCount &&
         responseLines[typingLine].length() == 0) {
    ++typingLine;
    typingColumn = 0;
  }

  if (typingLine >= responseLineCount) {
    responseTyping = false;
    responseStage = RESPONSE_NONE;
    armIdleTimer();
    Serial.println(F("[ANIMA] Respuesta terminada; reposo en 10 segundos"));
    return;
  }

  const uint8_t row = typingLine - visibleStartLine;
  const String& line = responseLines[typingLine];
  const char c = line.charAt(typingColumn);

  tft.setTextSize(1);
  tft.setTextColor(ST77XX_WHITE);
  tft.setCursor(10 + typingColumn * 6, 42 + row * 9);
  tft.write((uint8_t)c);

  ++typingColumn;
  if (typingColumn >= line.length()) {
    ++typingLine;
    typingColumn = 0;
  }
}

// =====================================================
// Iniciar transición cuando llega la respuesta del modelo
// =====================================================
void startResponseTransition(const String& answer) {
  cancelIdleTimer();
  prepareResponse(answer);
  drawState(STATE_RESPONDING);
  responseStage = RESPONSE_SHOWING_WAVE;
  responseDeadline = millis() + 900;
}

void updateResponseTransition() {
  if (responseStage == RESPONSE_SHOWING_WAVE &&
      (long)(millis() - responseDeadline) >= 0) {
    drawState(STATE_COMPLETE);
    responseStage = RESPONSE_SHOWING_COMPLETE;
    responseDeadline = millis() + 850;
    return;
  }

  if (responseStage == RESPONSE_SHOWING_COMPLETE &&
      (long)(millis() - responseDeadline) >= 0) {
    beginResponseTyping();
  }
}

// =====================================================
// Convertir estados recibidos por WebSocket a pantallas
// =====================================================
void handleStatus(const char* value) {
  if (!value || !*value) return;

  if (!strcmp(value, "thinking") || !strcmp(value, "processing")) {
    cancelIdleTimer();
    drawState(STATE_THINKING);
  } else if (!strcmp(value, "listening") || !strcmp(value, "te_escucho")) {
    cancelIdleTimer();
    drawState(STATE_LISTENING);
  } else if (!strcmp(value, "responding") || !strcmp(value, "speaking")) {
    cancelIdleTimer();
    drawState(STATE_RESPONDING);
  } else if (!strcmp(value, "idle") || !strcmp(value, "ready") ||
             !strcmp(value, "connected")) {
    // No interrumpir una respuesta ni adelantar el reposo si el servidor
    // emite "idle/ready" al terminar de generar el mensaje.
    if (responseStage != RESPONSE_NONE || responseTyping) return;
    if (currentState == STATE_COMPLETE && responseLineCount > 0) {
      if (!idleTimerActive) armIdleTimer();
      return;
    }
    drawState(STATE_READY);
    armIdleTimer();
  } else if (!strcmp(value, "muted") || !strcmp(value, "muteada")) {
    cancelIdleTimer();
    drawState(STATE_MUTED);
  } else if (!strcmp(value, "updating") || !strcmp(value, "updating_system")) {
    cancelIdleTimer();
    drawState(STATE_UPDATING);
  } else if (!strcmp(value, "completed") || !strcmp(value, "complete")) {
    if (responseStage != RESPONSE_NONE || responseTyping) return;
    if (currentState == STATE_COMPLETE && responseLineCount > 0) {
      if (!idleTimerActive) armIdleTimer();
      return;
    }
    drawState(STATE_COMPLETE);
    armIdleTimer();
  } else if (!strcmp(value, "disconnected") || !strcmp(value, "offline")) {
    cancelIdleTimer();
    drawState(STATE_OFFLINE);
  } else if (!strcmp(value, "error")) {
    cancelIdleTimer();
    drawState(STATE_ERROR);
  } else if (!strcmp(value, "starting") || !strcmp(value, "initializing")) {
    cancelIdleTimer();
    drawState(STATE_BOOT);
  } else {
    // Un estado desconocido no debe dejar una pantalla antigua.
    cancelIdleTimer();
    drawState(STATE_READY);
    armIdleTimer();
  }
}

// =====================================================
// Evento WebSocket
// =====================================================
void webSocketEvent(WStype_t type, uint8_t* payload, size_t length) {
  if (type == WStype_CONNECTED) {
    Serial.println(F("WebSocket conectado"));
    wsConnected = true;
    sleepStop();
    drawState(STATE_READY);
    armIdleTimer();
    return;
  }

  if (type == WStype_DISCONNECTED) {
    Serial.println(F("WebSocket desconectado"));
    wsConnected = false;
    sleepStop();
    cancelIdleTimer();
    drawState(STATE_OFFLINE);
    return;
  }

  if (type == WStype_ERROR) {
    Serial.println(F("Error WebSocket"));
    sleepStop();
    cancelIdleTimer();
    drawState(STATE_ERROR);
    return;
  }

  if (type != WStype_TEXT) return;

  JsonDocument doc;
  DeserializationError jsonError = deserializeJson(doc, payload, length);
  if (jsonError) {
    Serial.print(F("Error JSON: "));
    Serial.println(jsonError.c_str());
    sleepStop();
    cancelIdleTimer();
    drawState(STATE_ERROR);
    return;
  }

  const char* kind = doc["type"] | "";

  if (!strcmp(kind, "status")) {
    const char* value = doc["value"] | "";
    Serial.print(F("Estado ANIMA: "));
    Serial.println(value);
    sleepStop();
    handleStatus(value);
    return;
  }

  if (!strcmp(kind, "response")) {
    const char* answer = doc["text"] | "";
    Serial.println(F("Respuesta recibida:"));
    Serial.println(answer);

    sleepStop();
    if (answer[0]) {
      startResponseTransition(String(answer));
    } else {
      drawState(STATE_COMPLETE);
      armIdleTimer();
    }
    return;
  }

  if (!strcmp(kind, "error")) {
    const char* errorText = doc["text"] | "Error del modelo";
    Serial.print(F("Error del puente: "));
    Serial.println(errorText);
    sleepStop();
    cancelIdleTimer();
    drawState(STATE_ERROR);
    return;
  }
}

// =====================================================
// Setup
// =====================================================
void setup() {
  Serial.begin(115200);
  delay(100);

  tft.initR(INITR_BLACKTAB);
  tft.setRotation(1);

  // Splash de marca ANIMA durante 2 segundos en cada arranque.
  tft.drawRGBBitmap(0, 0, animaSplash, SCREEN_W, SCREEN_H);
  delay(2000);

  // Después del splash comienza el arranque normal.
  drawState(STATE_BOOT);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.print(F("Conectando WiFi"));
  while (WiFi.status() != WL_CONNECTED) {
    delay(300);
    Serial.print('.');
  }

  Serial.println();
  Serial.print(F("WiFi conectado. IP NodeMCU: "));
  Serial.println(WiFi.localIP());

  webSocket.begin(BRIDGE_HOST, BRIDGE_PORT, "/ws");
  webSocket.onEvent(webSocketEvent);
  webSocket.setReconnectInterval(3000);

  drawState(STATE_BOOT);
  armIdleTimer();
}

// =====================================================
// Loop: nunca bloqueamos durante las animaciones
// =====================================================
void loop() {
  webSocket.loop();

  updateResponseTransition();
  animateResponseText();
  sleepTick();

  const unsigned long now = millis();

  if (idleTimerActive && !sleepActive && wsConnected &&
      !responseTyping && responseStage == RESPONSE_NONE) {

    // Fase 2: respiro animado (el "gif" del rostro).
    if (now - lastInteractionAt >= IDLE_SLEEP_MS) {
      idleTimerActive = false;
      Serial.println(F("[ANIMA] Sin actividad: respiro en reposo"));
      sleepStart();
    }
    // Fase 1: pantalla REPOSO estática.
    else if (now - lastInteractionAt >= IDLE_READY_MS &&
             currentState != STATE_READY) {
      Serial.println(F("[ANIMA] 10 segundos sin actividad: pantalla de reposo"));
      drawState(STATE_READY);
    }
  }

  if (now - lastPing >= 20000) {
    lastPing = now;
    if (webSocket.isConnected()) {
      webSocket.sendTXT("ping");
    }
  }
}
