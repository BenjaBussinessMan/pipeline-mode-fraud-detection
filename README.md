# Real-Time Streaming Pipeline & Fraud Detection API

![Python](https://img.shields.io/badge/Python-3.12-3776AB) ![Kafka](https://img.shields.io/badge/Apache%20Kafka-3.8-231F20) ![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688) ![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1) ![Docker](https://img.shields.io/badge/Docker-multi--stage-2496ED)

## Problema

Detectar transacciones anomalas en tiempo real, antes de que impacten el balance financiero.

## Solucion

Un pipeline de ingesta en streaming con Kafka, consumidores en Python que puntuan cada transaccion, y una API de inferencia ligera con FastAPI. Todo el entorno se levanta con un solo comando.

```
 +-----------+    key=account_id    +---------------------+
 | Producer  | -------------------> |  Kafka              |
 | (simulador)|                     |  transactions (x3)  |
 +-----------+                      |  transactions.dlq   |
                                    +----------+----------+
                                               |
                                               v
                                    +---------------------+      +--------------+
                                    | Consumer (Python)   | ---> |  PostgreSQL  |
                                    | valida, puntua,     |      | transactions |
                                    | persiste, commit    |      | profiles     |
                                    +---------------------+      +------+-------+
                                                                        ^
                                    +---------------------+             |
                         HTTP  ---> | FastAPI (inferencia)| ------------+
                                    | /v1/score, /flagged |
                                    +---------------------+
```

## Inicio rapido

Requisito: Docker con Compose v2.

```bash
docker compose up --build -d              # kafka, postgres, api, consumer
docker compose --profile sim up -d producer   # trafico simulado con fraude inyectado
docker compose logs -f consumer           # alertas de fraude en vivo

curl localhost:8000/v1/stats
curl "localhost:8000/v1/transactions/flagged?limit=5"
```

Documentacion interactiva: <http://localhost:8000/docs>

Probar el scoring de forma directa (no modifica estado):

```bash
curl -X POST localhost:8000/v1/score -H "Content-Type: application/json" -d '{
  "transaction_id": "demo-1", "account_id": "acc-001", "amount": 9500,
  "merchant_category": "crypto", "country": "ES",
  "timestamp": "2025-03-10T03:15:00Z"
}'
```

## Endpoints

| Metodo | Ruta | Descripcion |
|--------|------|-------------|
| GET | `/health` | Estado del servicio y de la base de datos (503 si cae) |
| POST | `/v1/score` | Puntua una transaccion contra el perfil de su cuenta, sin persistir |
| GET | `/v1/transactions/flagged` | Ultimas transacciones marcadas como fraude |
| GET | `/v1/accounts/{id}/profile` | Perfil estadistico de una cuenta |
| GET | `/v1/stats` | Totales y tasa de fraude |

## Motor de scoring

Modelo ligero y explicable, sin dependencias de ML pesadas, pensado para latencia baja. Cada senal produce un valor entre 0 y 1 y se combinan con noisy-OR: `score = 1 - prod(1 - s_i)`. Una transaccion es fraude si `score >= FRAUD_THRESHOLD` (0.7 por defecto).

| Senal | Regla |
|-------|-------|
| Monto atipico | z-score contra media y desviacion de la cuenta (Welford incremental, minimo 5 transacciones); antes, umbral absoluto de 5000 |
| Velocidad | 5 o mas transacciones en 60 s |
| Viaje imposible | cambio de pais en menos de 1 hora |
| Contexto | categoria de riesgo (crypto, gambling, wire_transfer) y horario nocturno UTC, con peso bajo |

Cada resultado incluye `reasons`, la lista de senales que contribuyeron. Las transacciones marcadas como fraude no actualizan la media y desviacion de la cuenta, para que un atacante no pueda "entrenar" el perfil.

## Decisiones de diseno

- **Orden por cuenta**: el productor usa `account_id` como key, por lo que todas las transacciones de una cuenta caen en la misma particion y se procesan en orden. Esto hace seguro el ciclo leer perfil, puntuar, escribir perfil sin locks.
- **At-least-once + idempotencia**: el consumer hace commit del offset solo despues de persistir. Una re-entrega no duplica nada porque `transaction_id` es clave primaria y el perfil solo se actualiza cuando la insercion es nueva (misma transaccion SQL).
- **Dead-letter queue**: los mensajes que no validan contra el esquema van a `transactions.dlq` con el error en un header, en lugar de bloquear la particion.
- **Nucleo puro**: `scoring.py` no hace I/O; el repositorio es un `Protocol` con implementacion Postgres y en memoria, lo que permite probar API y consumer sin infraestructura.
- **Una imagen, varios comandos**: API, consumer y producer comparten imagen y paquete `fraud`.

## Dockerfile multi-stage

| Stage | Proposito |
|-------|-----------|
| `builder` | Crea un virtualenv con las dependencias de produccion |
| `test` | Hereda `builder`, instala pytest y ejecuta la suite; falla el build si hay errores |
| `runtime` | `python:3.12-slim`, copia solo el venv y `src`, usuario no root, `HEALTHCHECK` |

```bash
docker build --target test .      # corre las pruebas dentro del build
docker build --target runtime -t fraud-detection .
```

## Pruebas

```bash
python -m venv .venv && source .venv/bin/activate   # en Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest --cov
```

Cubren el motor de scoring (cada senal, combinacion, umbral, perfil incremental), el servicio (idempotencia, aislamiento del dry-run), la API (validacion 422, 404, 503) y el consumer (mensajes validos, invalidos y re-entregados).

## Estructura

```
src/fraud/
  scoring.py      motor de scoring y perfil de cuenta
  service.py      orquestacion: perfil -> score -> persistencia
  repository.py   Postgres y en memoria
  consumer.py     consumidor Kafka con DLQ
  producer.py     simulador de transacciones
  api/main.py     aplicacion FastAPI
db/init.sql       esquema
tests/            suite Pytest
```