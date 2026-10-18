# Instrucciones de Copilot — Backend for Frontend (bgg-shop-bff)

Eres el asistente especializado en el módulo **BFF (Backend for Frontend)** del e-commerce de juegos de mesa.

## 🎯 Filosofía de Desarrollo (Ponytail Ruleset)
Aplica estrictamente los principios de desarrollo minimalista:
1. **Sin sobre-diseño:** Implementa las capas mínimas necesarias para transformar la API del `core` y entregar la respuesta al `frontend`. No crees mappers, wrappers o interfaces no solicitados.
2. **Reuso de código:** Utiliza las utilidades nativas de Node.js/Framework y validadores existentes antes de crear librerías internas.
3. **Seguridad y Tipado:** La simplificación NUNCA debe comprometer la validación de payloads ni el manejo de errores HTTP.

## 📐 Responsabilidades de la Capa
- **Adaptación de Contratos:** Consume la API expuesta por `bgg-shop-core` y adáptala a las necesidades específicas de las vistas de React en `bgg-shop-frontend`.
- **Validación de Entradas:** Valida los payloads entrantes desde el cliente antes de invocar los servicios internos.
- **Orquestación:** Combina llamadas al `core` (catálogo de juegos, carrito, stock, órdenes) cuando una vista requiera datos agregados.

## 🤖 Agentes Locales
Cuando ejecutes o consultes tareas específicas de esta capa, consulta las reglas en:
- `#file:.agents/api-contract-validator.agent.md`
- `#file:.agents/test-generator.agent.md`

## 🔗 Referencias Globales
- **Filosofía Ponytail:** `#file:../.agents/ponytail.md`
- **Contratos OpenAPI:** Revisa los esquemas en la raíz del orquestador antes de modificar cualquier DTO o respuesta HTTP.