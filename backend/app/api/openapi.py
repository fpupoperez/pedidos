"""Text published in the OpenAPI document for a future MCP adapter."""

OPENAPI_DESCRIPTION = """
JSON API for order imports and read-only questions.

Every JSON response uses the same envelope: session_auth, errors, success, and data.
When success is false, data is null and errors[0].msg explains the failure.
There is no top-level detail property.

An MCP adapter should expose each operationId as one tool and fill arguments only from this schema.

get_health reports that the API process is running. It does not check the database or NATS.

create_import accepts one CSV in the multipart field named file. The response is 202.
With inline delivery the task in that response is already terminal. Poll get_task otherwise.
summary.phase is importing while status is processing. importedRows stays 0 until the insert commits.
A second upload of the same bytes returns 409 and names the existing task id.
cancel_task is refused with 409 once the task is completed, failed, or cancelled.
retry_task republishes publish_failed, retries_exhausted, and a processing task older than the ack wait.
download_task_file returns the original CSV bytes, not the JSON envelope.
list_task_rejections lists lines that were not imported. Those rows stay after cancel.
list_orders reads committed rows. Pass taskId to see one file.

Do not send a JSON body on GET.

Do not retry 400, 404, 409, 413, or 422 until the arguments change.
500 and 502 may be retried once.
"""

OPENAPI_TAGS = [
    {
        "name": "Status",
        "description": "Process liveness. get_health does not read orders.",
    },
    {"name": "Imports", "description": "Upload a CSV. create_import returns a task id."},
    {"name": "Tasks", "description": "Poll status, cancel, retry, and download the original file."},
    {"name": "Orders", "description": "Read orders an import has committed."},
]
