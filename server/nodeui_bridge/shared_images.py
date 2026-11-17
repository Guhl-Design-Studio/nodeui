"""Omit unfilled Shared Input wires before ComfyUI validates or queues a job."""
import copy
import json

from aiohttp import web

from .share_nodes import shared_image_paths


def prepare_shared_images(body):
    if not isinstance(body, dict):
        raise ValueError("Submit a workflow as a JSON object.")
    prompt = body.get("prompt")
    if not isinstance(prompt, dict):
        return body
    counts = {}
    for node_id, node in prompt.items():
        if not isinstance(node, dict):
            continue
        if node.get("class_type") != "NodeUISharedInput":
            continue
        inputs = node.get("inputs", {})
        if not isinstance(inputs, dict):
            raise ValueError("Shared Input needs named image and prompt inputs.")
        counts[node_id] = shared_image_paths(inputs.get("image", ""), inputs.get("image_paths", ""))
    if not counts:
        return body
    result = copy.deepcopy(body)
    import nodes

    def schema_for(node):
        definition = nodes.NODE_CLASS_MAPPINGS.get(node.get("class_type"))
        schema = definition.INPUT_TYPES() if definition else {}
        if definition and hasattr(definition, "GET_SCHEMA"):
            from comfy_api.latest import _io
            schema, _, _ = _io.get_finalized_class_inputs(schema, node.get("inputs", {}))
        return definition, schema

    unavailable_nodes = set()

    def unavailable(value):
        if not (isinstance(value, list) and len(value) == 2 and isinstance(value[0], str)
                and type(value[1]) is int):
            return False
        source, slot = value
        if source in unavailable_nodes:
            return True
        if source not in counts or slot == 1:
            return False
        index = 0 if slot == 0 else slot - 1
        return not (0 <= index < len(counts[source]) and counts[source][index] is not None)

    def required_now(spec):
        options = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
        return not options.get("lazy", False)

    # A missing required image makes every output of a processing node absent.
    # Iterate independently of prompt order, stopping at optional/lazy inputs.
    # Actual output nodes must still reject missing required inputs.
    changed = True
    while changed:
        changed = False
        for node_id, node in result["prompt"].items():
            if node_id in unavailable_nodes or not isinstance(node, dict):
                continue
            inputs = node.get("inputs", {})
            if not isinstance(inputs, dict) or not any(unavailable(value) for value in inputs.values()):
                continue
            definition, schema = schema_for(node)
            if definition and getattr(definition, "OUTPUT_NODE", False):
                continue
            if any(name in inputs and unavailable(inputs[name]) and required_now(spec)
                   for name, spec in schema.get("required", {}).items()):
                unavailable_nodes.add(node_id)
                changed = True

    for node_id in unavailable_nodes:
        del result["prompt"][node_id]
    for node in result["prompt"].values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs", {})
        if not isinstance(inputs, dict):
            continue
        for name, value in tuple(inputs.items()):
            if not unavailable(value):
                continue
            _, schema = schema_for(node)
            spec = schema.get("required", {}).get(name)
            if spec is not None and required_now(spec):
                title = node.get("_meta", {}).get("title", node.get("class_type"))
                raise ValueError(f"{title}: select an image for the required {name} input or disconnect that Shared Input output.")
            del inputs[name]
    return result


@web.middleware
async def shared_images_middleware(request, handler):
    if request.method == "POST" and request.path in {
        "/prompt", "/api/prompt", "/nodeui/v1/share/runs", "/comfymobile/v1/share/runs"
    }:
        try:
            body = await request.json()
            prepared = prepare_shared_images(body)
        except (ValueError, TypeError) as error:
            return web.json_response({"error": "invalid_shared_images", "message": str(error)}, status=400)
        if prepared is not body:
            # aiohttp handlers subsequently read this normalized request body.
            request._read_bytes = json.dumps(prepared).encode("utf-8")
    return await handler(request)
