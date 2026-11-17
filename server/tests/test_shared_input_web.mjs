// Run with: node --test server/tests/test_shared_input_web.mjs
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../nodeui_bridge/web/shared_input.js", import.meta.url), "utf8")
    .replace(/^import .*;\n/gm, "");

function editor({paths = ["first.png", "second.png", "third.png", "fourth.png"], fetch} = {}) {
    const requests = [], errors = [], menus = [], changes = [];
    let extension;
    const app = {
        registerExtension(value) { extension = value; },
        ui: {dialog: {show(message) { errors.push(message); }}},
        canvas: {
            scale: 1, offset: [0, 0],
            adjustMouseEvent(event) {
                event.canvasX = event.clientX / this.scale - this.offset[0];
                event.canvasY = event.clientY / this.scale - this.offset[1];
            },
        },
    };
    const api = {
        apiURL(path) { return path; },
        async fetchApi(path, options) {
            requests.push({path, options});
            return fetch ? await fetch(path, options) : {
                ok: true,
                json: async () => ({name: "dropped.png", subfolder: "uploads", type: "input"}),
            };
        },
    };
    class Node {
        constructor() {
            this.comfyClass = "NodeUISharedInput";
            this.widgets = [{name: "image", value: paths[0] ?? "", options: {values: [...paths]}},
                {name: "prompt", value: "Keep this prompt"}, {name: "image_paths"}];
            this.properties = {nodeui_shared_images: [...paths]};
            this.outputs = ["IMAGE", "STRING", "IMAGE", "IMAGE", "IMAGE"]
                .map((type, slot) => ({type, links: slot === 1 ? [] : [slot + 1]}));
            this.pos = [100, 50];
            this.size = [480, 562];
            this.graph = {beforeChange() { changes.push("before"); }, afterChange() { changes.push("after"); }};
        }
        addOutput(name, type) { this.outputs.push({name, type, links: []}); }
        computeSize() { return [this.size[0], 562]; }
        setSize(value) { this.size = value; }
        setDirtyCanvas() {}
        addCustomWidget(widget) { this.widgets.push(widget); return widget; }
    }
    const document = {createElement() {
        return {textContent: "", get innerHTML() {
            return this.textContent.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
        }};
    }};
    const context = vm.createContext({app, api, document, FormData, URL, URLSearchParams,
        location: {href: "http://localhost:8188/"}, Image: class {},
        LiteGraph: {NODE_SLOT_HEIGHT: 20, ContextMenu: class {
            constructor(items, options) { menus.push({items, options}); }
        }},
    });
    vm.runInContext(source, context);
    extension.beforeRegisterNodeDef(Node, {name: "NodeUISharedInput"});
    const node = new Node();
    node.onNodeCreated();
    extension.nodeCreated(node);
    const widget = node.widgets.find(w => w.name === "nodeui_slot_previews");
    function draw(width = node.size[0]) {
        const ctx = new Proxy({}, {get: (target, key) => target[key] ?? (() => {})});
        widget.draw(ctx, node, width, 194);
    }
    draw();
    function event(x, y, files = [], data = {}) {
        return {type: "pointerdown", clientX: (node.pos[0] + x + app.canvas.offset[0]) * app.canvas.scale,
            clientY: (node.pos[1] + y + app.canvas.offset[1]) * app.canvas.scale,
            dataTransfer: {files, items: files.map(file => ({kind: "file", type: file.type})),
                types: Object.keys(data), getData: type => data[type] ?? ""}};
    }
    return {node, widget, app, requests, errors, menus, changes, draw, event,
        paths: () => JSON.parse(JSON.stringify(node.properties.nodeui_shared_images)),
        serializedPaths: () => node.widgets.find(w => w.name === "image_paths").serializeValue()};
}

const png = () => new File(["image fixture"], "local.png", {type: "image/png"});
const tick = () => new Promise(resolve => setImmediate(resolve));

test("dropping into a later image area uploads only that numbered slot, including after pan and zoom", async () => {
    const e = editor();
    e.app.canvas.scale = 0.6;
    e.app.canvas.offset = [270, -15];
    const drop = e.event(350, 420, [png()]); // Second row, right: image 4.
    assert.equal(e.node.onDragOver(drop), true);
    assert.equal(await e.node.onDragDrop(drop), true);
    assert.deepEqual(e.paths(), ["first.png", "second.png", "third.png", "uploads/dropped.png"]);
    assert.equal(e.requests.length, 1);
    const {path, options} = e.requests[0];
    assert.equal(path, "/upload/image");
    assert.equal(options.body.get("image").name, "local.png");
    assert.equal(options.body.get("overwrite"), "false");
    assert.equal(options.body.get("type"), "input");
    assert.deepEqual(e.changes, ["before", "after"]);
    assert.deepEqual(JSON.parse(e.serializedPaths()), e.paths());
});

test("replacing image 1 preserves later images and a missing middle slot", async () => {
    const e = editor({paths: ["old.png", null, "third.png"]});
    await e.node.onDragDrop(e.event(100, 270, [png()]));
    assert.deepEqual(e.paths(), ["uploads/dropped.png", null, "third.png"]);
    assert.equal(e.node.widgets[0].value, "uploads/dropped.png");
    assert.equal(e.node.widgets[1].value, "Keep this prompt");
});

test("drops outside image areas, over disconnected slots, and non-image files leave assignments alone", async () => {
    const e = editor();
    const initial = e.paths();
    for (const drop of [e.event(100, 150, [png()]), e.event(100, 270, [new File(["{}"], "workflow.json", {type: "application/json"})])]) {
        assert.equal(e.node.onDragOver(drop), false);
        assert.equal(await e.node.onDragDrop(drop), false);
    }
    e.node.outputs[2].links = [];
    const staleArea = e.event(350, 270, [png()]);
    assert.equal(e.node.onDragOver(staleArea), false);
    assert.equal(await e.node.onDragDrop(staleArea), false);
    assert.deepEqual(e.paths(), initial);
    assert.equal(e.requests.length, 0);
});

test("one-column layouts still target image 2 without shifting nullable slots", async () => {
    const e = editor({paths: [null, null, "third.png"]});
    e.node.size[0] = 240;
    e.draw();
    await e.node.onDragDrop(e.event(100, 420, [png()]));
    assert.deepEqual(e.paths(), [null, "uploads/dropped.png", "third.png"]);
    assert.equal(e.node.widgets[0].value, "");
});

test("upload failures and multiple-file drops preserve all assignments", async () => {
    const e = editor({fetch: async () => ({ok: false, status: 503})});
    const initial = e.paths();
    assert.equal(await e.node.onDragDrop(e.event(350, 270, [png()])), true);
    assert.match(e.errors[0], /503/);
    assert.equal(e.node.onDragOver(e.event(350, 270, [png()])), true);
    assert.equal(await e.node.onDragDrop(e.event(350, 270, [png(), png()])), true);
    assert.match(e.errors[1], /one image/);
    assert.equal(e.requests.length, 1);
    assert.deepEqual(e.paths(), initial);
    assert.deepEqual(e.changes, []);
});

test("uploads to different slots can finish out of order without losing either assignment", async () => {
    const complete = [];
    const e = editor({fetch: () => new Promise(resolve => complete.push(name => resolve({
        ok: true, json: async () => ({name}),
    })))});
    const second = e.node.onDragDrop(e.event(350, 270, [png()]));
    const third = e.node.onDragDrop(e.event(100, 420, [png()]));
    assert.equal(e.node.onDragOver(e.event(350, 270, [png()])), false);
    complete[1]("third-upload.png");
    await third;
    complete[0]("second-upload.png");
    await second;
    assert.deepEqual(e.paths(), ["first.png", "second-upload.png", "third-upload.png", "fourth.png"]);
});

test("Select refreshes uploaded images and assigns the selected raw filename only to its slot", async () => {
    const filename = "folder/<new & uploaded>.png";
    const e = editor({fetch: async () => ({ok: true, json: async () => ({NodeUISharedInput: {
        input: {required: {image: [["from-another-node.png", filename], {image_upload: true}]}},
    }})})});
    assert.equal(e.widget.mouse(e.event(350, 336), [350, 336]), true);
    await tick();
    assert.equal(e.requests[0].path, "/object_info/NodeUISharedInput");
    assert.equal(e.requests[0].options.cache, "no-store");
    assert.equal(e.menus[0].options.title, "Select image 2");
    assert.equal(e.menus[0].items[1].content, "folder/&lt;new &amp; uploaded&gt;.png");
    e.menus[0].items[1].callback();
    assert.deepEqual(e.paths(), ["first.png", filename, "third.png", "fourth.png"]);
    assert.equal(e.requests.length, 1);
    assert.deepEqual(JSON.parse(e.serializedPaths()), e.paths());
});

test("an empty image library and a failed refresh show an error without changing images", async () => {
    for (const response of [{ok: false, status: 500}, {ok: true, json: async () => ({NodeUISharedInput: {
        input: {required: {image: [[], {}]}},
    }})}]) {
        const e = editor({fetch: async () => response});
        e.widget.mouse(e.event(350, 336), [350, 336]);
        await tick();
        assert.equal(e.errors.length, 1);
        assert.equal(e.menus.length, 0);
        assert.deepEqual(e.changes, []);
    }
});

test("ComfyUI asset and same-server view drops reuse images without uploading; external URLs are ignored", async () => {
    const e = editor();
    const asset = {filename: "result.png", subfolder: "batch", type: "output"};
    assert.equal(await e.node.onDragDrop(e.event(350, 270, [], {
        "application/x-comfy-asset-info": JSON.stringify(asset),
    })), true);
    assert.equal(e.paths()[1], "batch/result.png [output]");
    assert.equal(await e.node.onDragDrop(e.event(100, 270, [], {
        "text/uri-list": "http://localhost:8188/view?filename=existing.png&subfolder=uploads&type=input",
    })), true);
    assert.equal(e.paths()[0], "uploads/existing.png");
    assert.equal(await e.node.onDragDrop(e.event(100, 270, [], {
        "text/uri-list": "https://example.com/view?filename=external.png",
    })), false);
    assert.equal(e.paths()[0], "uploads/existing.png");
    assert.equal(await e.node.onDragDrop(e.event(100, 270, [], {
        "application/x-comfy-asset-info": JSON.stringify({filename: "video.mp4", type: "input", media_kind: "video"}),
    })), false);
    assert.equal(e.requests.length, 0);
});
