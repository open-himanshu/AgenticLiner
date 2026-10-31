# AgenticLiner API contract v1

This document defines a proposed JSON-over-HTTP contract for the mock event
planning API. Monetary amounts are integer rupees. Dates use `YYYY-MM-DD`;
hours use 24-hour integers, with `end_hour` exclusive. A booking is never
partially committed: checkout conflicts roll back the entire request.

All responses use `application/json`.

## `POST /brief`

Submit an event brief for planning. This endpoint describes the validated
brief and planning result; it does not reserve a venue or equipment.

### Request JSON

```json
{
  "event_type": "dance",
  "description": "Dance performance for students",
  "date": "2026-11-06",
  "start_hour": 18,
  "end_hour": 20,
  "headcount": 150,
  "organiser": "Himanshu",
  "budget": 20000,
  "requirements": ["stage lights", "sound system", "wireless mic"]
}
```

`event_type`, `date`, `start_hour`, `end_hour`, `headcount`, and `budget` are
required. `description`, `organiser`, and `requirements` are optional.

### Success — `200 OK`

```json
{
  "api_version": "v1",
  "brief_id": "brief_01",
  "status": "ready",
  "event_type": "dance",
  "date": "2026-11-06",
  "start_hour": 18,
  "end_hour": 20,
  "headcount": 150,
  "budget": 20000,
  "suggested_venue": {
    "id": "STG-C",
    "name": "Open Stage C",
    "capacity": 300,
    "price_per_hour": 800
  },
  "suggested_items": [
    {"id": "stage-lights", "name": "stage lights", "quantity": 4},
    {"id": "sound-system", "name": "sound system", "quantity": 1},
    {"id": "wireless-mic", "name": "wireless mic", "quantity": 2}
  ],
  "estimated_total": 6300,
  "questions": []
}
```

### Error — `400 Bad Request`

```json
{
  "api_version": "v1",
  "error": {
    "code": "INVALID_BRIEF",
    "message": "The brief has invalid or missing fields.",
    "details": [
      {"field": "headcount", "message": "Must be a positive integer."}
    ]
  }
}
```

### Conflict — `409 Conflict`

```json
{
  "api_version": "v1",
  "error": {
    "code": "NO_VIABLE_PLAN",
    "message": "No plan fits the requested time, capacity, and budget.",
    "violations": ["No available venue can host 450 people."],
    "suggestions": [
      "Reduce the headcount to 400 or fewer.",
      "Choose another date or venue."
    ]
  }
}
```

## `GET /catalog`

Return the available categories, venues, and equipment. Optional query
parameters: `category` filters by category; `available_only=true` excludes
items with no stock.

### Request

```http
GET /catalog?category=audio_visual&available_only=true
```

### Success — `200 OK`

```json
{
  "api_version": "v1",
  "categories": ["venues", "audio_visual", "staffing", "safety", "utilities"],
  "items": [
    {
      "id": "projector",
      "category": "audio_visual",
      "name": "projector",
      "price": 500,
      "stock": 3,
      "suggested_by_ai": true
    },
    {
      "id": "wireless-mic",
      "category": "audio_visual",
      "name": "wireless mic",
      "price": 300,
      "stock": 6,
      "suggested_by_ai": true
    }
  ]
}
```

### Error — `400 Bad Request`

```json
{
  "api_version": "v1",
  "error": {
    "code": "INVALID_CATEGORY",
    "message": "The requested catalog category does not exist."
  }
}
```

### Conflict — `409 Conflict`

```json
{
  "api_version": "v1",
  "error": {
    "code": "CATALOG_UNAVAILABLE",
    "message": "The catalog cannot be served right now.",
    "violations": ["The inventory snapshot is being refreshed."],
    "suggestions": ["Retry the request shortly."]
  }
}
```

## `POST /checkout`

Atomically reserve a venue and equipment for an event. All requested stock,
capacity, schedule, date, and budget constraints must pass or the whole
checkout is rolled back.

### Request JSON

```json
{
  "brief_id": "brief_01",
  "venue_id": "STG-C",
  "date": "2026-11-06",
  "start_hour": 18,
  "end_hour": 20,
  "headcount": 150,
  "equipment": {
    "stage lights": 4,
    "sound system": 1,
    "wireless mic": 2
  },
  "budget": 20000,
  "organiser": "Himanshu"
}
```

Required fields are `venue_id`, `date`, `start_hour`, `end_hour`, `headcount`,
`equipment`, and `budget`. `brief_id` and `organiser` are optional.

### Success — `201 Created`

```json
{
  "api_version": "v1",
  "status": "committed",
  "checkout_id": "checkout_01",
  "booking": {
    "venue_id": "STG-C",
    "venue_name": "Open Stage C",
    "date": "2026-11-06",
    "start_hour": 18,
    "end_hour": 20,
    "headcount": 150,
    "equipment": {
      "stage lights": 4,
      "sound system": 1,
      "wireless mic": 2
    },
    "total_cost": 6300
  },
  "budget_remaining": 13700
}
```

### Error — `400 Bad Request`

```json
{
  "api_version": "v1",
  "error": {
    "code": "INVALID_CHECKOUT",
    "message": "The checkout has invalid or missing fields.",
    "details": [
      {"field": "date", "message": "Use a valid YYYY-MM-DD date."}
    ]
  }
}
```

### Conflict — `409 Conflict`

```json
{
  "api_version": "v1",
  "status": "rolled_back",
  "checkout_id": "checkout_02",
  "committed": false,
  "violations": [
    "The venue overlaps an existing booking.",
    "Requested 9 stage lights, but only 8 are in stock."
  ],
  "suggestions": [
    "Choose a different time or venue.",
    "Reduce stage lights to 8 or fewer."
  ]
}
```

## Error codes

| HTTP status | Code | Plain message |
|---|---|---|
| 400 | `INVALID_BRIEF` | The brief has invalid or missing fields. |
| 400 | `INVALID_CHECKOUT` | The checkout has invalid or missing fields. |
| 400 | `INVALID_CATEGORY` | The requested catalog category does not exist. |
| 401 | `UNAUTHORIZED` | Provide a valid API credential. |
| 404 | `NOT_FOUND` | The requested resource does not exist. |
| 409 | `NO_VIABLE_PLAN` | No plan fits the requested time, capacity, and budget. |
| 409 | `CATALOG_UNAVAILABLE` | The catalog cannot be served right now. |
| 409 | `BOOKING_CONFLICT` | The requested booking conflicts with availability, stock, or budget. |
| 429 | `RATE_LIMITED` | Too many requests; retry later. |
| 500 | `INTERNAL_ERROR` | The server could not complete the request. |
