#pragma once

// Credenciales de la red local para la NodeMCU.
// Copia este archivo a secrets.h y rellena tus datos:
//     cp include/secrets.example.h include/secrets.h
// secrets.h está en .gitignore y nunca debe subirse al repositorio.

// Red WiFi a la que se conecta la placa (solo 2,4 GHz en el ESP8266).
#define WIFI_SSID "CAMBIA_NOMBRE_WIFI"
#define WIFI_PASSWORD "CAMBIA_CLAVE_WIFI"

// IP LAN del PC que ejecuta la Chat API.
// Averíguala con: hostname -I   (usa la IP de tu red, no las virtuales)
#define BRIDGE_HOST "192.168.1.100"

// Puerto de la Chat API (el mismo que use uvicorn).
#define BRIDGE_PORT 8000
