# ⚡ BGG Shop - Backend-For-Frontend (`bgg-shop-bff`)

[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![Flask 3.0](https://img.shields.io/badge/Flask-3.0-black.svg)](https://flask.palletsprojects.com/)
[![Pandas 2.2](https://img.shields.io/badge/Pandas-2.2-150458.svg)](https://pandas.pydata.org/)
[![Architecture](https://img.shields.io/badge/Pattern-BFF%20Gateway-orange.svg)](https://microservices.io/patterns/apigateway.html)

## 📌 Descripción General

**`bgg-shop-bff`** es la capa de **orquestación, transformación de datos y API Gateway** de la plataforma e-commerce de juegos de mesa. 

Desarrollado con **Flask** y optimizado para análisis vectorizado con **Pandas**, actúa como el único punto de entrada HTTP para el cliente web (`bgg-shop-front`). Abstrae la complejidad de la API GraphQL del Core (`bgg-shop-core`), consolidando múltiples consultas en endpoints REST eficientes, filtrando payloads y adaptando la estructura de datos a las necesidades exactas de la interfaz de usuario.

---

## 🏗️ Arquitectura y Flujo de Datos

El BFF elimina el acoplamiento directo entre la interfaz web y el motor de dominio en Django:

[ bgg-shop-front ]  ──(REST / JSON)──>  [ bgg-shop-bff ]  ──(GraphQL)──>  [ bgg-shop-core ]
(React / Vite)                         (Flask Gateway)                   (Django / Saleor)
│
┌───────────┴───────────┐
▼                       ▼
[ Pandas Analytics ]    [ Health & Proxy ]

* **Prevención de Over/Under-Fetching:** Solicita a Saleor Core únicamente los campos requeridos por la vista activa.
* **Transformación al Vuelo (ETL In-Memory):** Filtra, agrega y normaliza DataFrames de productos y métricas antes de responder al cliente.
* **Seguridad & Aislamiento:** Oculta la infraestructura de persistencia interna y el esquema interno de GraphQL del navegador web.

---

## 🛠️ Tech Stack

* **Lenguaje:** Python 3.12+
* **Framework Web:** Flask 3.0+
* **Procesamiento de Datos:** Pandas 2.2+
* **Cliente HTTP:** `requests` / `httpx`
* **Contenerización:** Podman / Podman Compose (Rootless)

---

## 🚀 Inicio Rápido (Entorno Local con Podman)

### Prerrequisitos
* Podman y Podman Compose activos.
* El servicio `saleor_api` (`bgg-shop-core`) corriendo en `http://api:8000/graphql/`.

### 1. Clonar el Repositorio
```bash
git clone [https://github.com/tu-usuario/bgg-shop-bff.git](https://github.com/tu-usuario/bgg-shop-bff.git)
cd bgg-shop-bff