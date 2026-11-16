"""Text published in the OpenAPI document for a future MCP adapter."""

OPENAPI_DESCRIPTION = """
JSON API for order imports and read-only questions.

Every JSON response uses the same envelope: session_auth, errors, success, and data.
When success is false, data is null and errors[0].msg explains the failure.
There is no top-level detail property.

An MCP adapter should expose each operationId as one tool and fill arguments only from this schema.

get_health reports that the API process is running. It does not check the database or NATS.
Do not send a JSON body on GET.

Do not retry 400, 404, 409, 413, or 422 until the arguments change.
500 and 502 may be retried once.
"""

OPENAPI_TAGS = [
    {
        "name": "Status",
        "description": "Process liveness. get_health does not read orders.",
    },
]
