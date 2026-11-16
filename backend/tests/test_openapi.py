"""The OpenAPI document is complete enough for a future MCP adapter."""

from fastapi.testclient import TestClient

from app.main import create_app


def test_operations_and_properties_are_documented() -> None:
    """Every operation has a unique id, summary, and description. Every property has a description."""
    client = TestClient(create_app())
    schema = client.get("/api/v1/openapi.json").json()
    seen: set[str] = set()
    for path_item in schema["paths"].values():
        for operation in path_item.values():
            if not isinstance(operation, dict) or "operationId" not in operation:
                continue
            operation_id = operation["operationId"]
            assert operation_id not in seen
            seen.add(operation_id)
            assert operation.get("summary")
            assert operation.get("description")
    assert seen
    for name, component in schema["components"]["schemas"].items():
        for prop_name, prop in component.get("properties", {}).items():
            assert prop.get("description"), f"{name}.{prop_name} has no description"
