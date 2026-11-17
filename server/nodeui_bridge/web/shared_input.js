import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const galleries = new WeakMap();

function previewPaths(node) {
    const first = node.widgets?.find(w => w.name === "image")?.value || "";
    const paths = node.properties?.nodeui_shared_images;
    return Array.isArray(paths) && (paths[0] || "") === first ? paths : [first || null];
}

function connectedImages(node) {
    return (node.outputs ?? []).map((output, slot) => ({output, slot}))
        .filter(({output, slot}) => output.type === "IMAGE" &&
            (node.isOutputConnected?.(slot) ?? output.links?.length));
}

function setSlotImage(node, slot, path) {
    node.graph?.beforeChange();
    const paths = previewPaths(node).slice(), index = slot === 0 ? 0 : slot - 1;
    while (paths.length <= index) paths.push(null);
    paths[index] = path;
    if (index === 0) node.widgets.find(w => w.name === "image").value = path || "";
    node.properties ||= {};
    node.properties.nodeui_shared_images = paths;
    node.graph?.afterChange();
    growImageOutputs(node);
}

async function uploadSlotFile(node, slot, file) {
    const state = galleries.get(node);
    if (state?.uploading.has(slot)) return;
    state?.uploading.add(slot);
    node.setDirtyCanvas(true, true);
    try {
        const data = new FormData();
        data.append("image", file); data.append("type", "input");
        data.append("overwrite", "false");
        const response = await api.fetchApi("/upload/image", {method: "POST", body: data});
        if (!response.ok) throw new Error(`Upload failed (${response.status})`);
        const result = await response.json();
        const path = [result.subfolder, result.name].filter(Boolean).join("/");
        if (!result.name) throw new Error("The server did not return an image filename.");
        const picker = node.widgets.find(w => w.name === "image");
        const choices = picker.options?.values;
        if (Array.isArray(choices) && !choices.includes(path)) choices.push(path);
        setSlotImage(node, slot, path);
    } catch (error) { app.ui.dialog.show(String(error.message || error)); }
    finally {
        state?.uploading.delete(slot);
        node.setDirtyCanvas(true, true);
    }
}

function uploadSlot(node, slot) {
    const input = document.createElement("input");
    input.type = "file"; input.accept = "image/*";
    input.style.display = "none";
    document.body.appendChild(input);
    input.oncancel = () => input.remove();
    input.onchange = async () => {
        const file = input.files?.[0];
        if (!file) { input.remove(); return; }
        try { await uploadSlotFile(node, slot, file); }
        finally { input.remove(); }
    };
    input.click();
}

async function selectSlot(node, slot, event) {
    try {
        // Refresh so images uploaded by another node or device are also available.
        const response = await api.fetchApi("/object_info/NodeUISharedInput", {cache: "no-store"});
        if (!response.ok) throw new Error(`Could not load uploaded images (${response.status})`);
        const definition = (await response.json()).NodeUISharedInput;
        const image = definition?.input?.required?.image;
        const values = Array.isArray(image?.[0]) ? image[0] : image?.[1]?.options;
        const choices = Array.isArray(values) ? [...new Set(values.filter(v => typeof v === "string" && v))] : [];
        if (!choices.length) throw new Error("No uploaded images are available. Upload an image first.");
        const label = document.createElement("span");
        new LiteGraph.ContextMenu(choices.map(path => {
            label.textContent = path;
            return {content: label.innerHTML, callback: () => setSlotImage(node, slot, path)};
        }), {event, title: `Select image ${slot === 0 ? 1 : slot}`, className: "dark"});
    } catch (error) { app.ui.dialog.show(String(error.message || error)); }
}

function imageDropArea(node, event) {
    app.canvas.adjustMouseEvent(event);
    const x = event.canvasX - node.pos[0], y = event.canvasY - node.pos[1];
    return galleries.get(node)?.areas.find(area => x >= area.x && x <= area.x + area.w &&
        y >= area.y && y <= area.y + area.h && connectedImages(node).some(({slot}) => slot === area.slot));
}

function isImageFile(file) {
    return file.type?.startsWith("image/") || (!file.type && /\.(png|jpe?g|webp|gif|bmp|tiff?|avif|heic|heif)$/i.test(file.name));
}

function droppedImagePath(transfer) {
    let image;
    try { image = JSON.parse(transfer.getData("application/x-comfy-asset-info")); } catch { /* File or URL drop. */ }
    if (!image?.filename) {
        const uri = transfer.getData("text/uri-list").split(/\r?\n/).find(line => line && !line.startsWith("#"));
        if (!uri) return null;
        try {
            const url = new URL(uri, location.href), view = new URL(api.apiURL("/view"), location.href);
            if (url.origin !== view.origin || url.pathname !== view.pathname) return null;
            image = Object.fromEntries(url.searchParams);
        } catch { return null; }
    }
    if (typeof image.filename !== "string" || !isImageFile({name: image.filename}) ||
        (image.media_kind && image.media_kind !== "image") ||
        (image.type && !["input", "output", "temp"].includes(image.type))) return null;
    const path = [image.subfolder, image.filename].filter(Boolean).join("/");
    return path + (image.type && image.type !== "input" ? ` [${image.type}]` : "");
}

function addSlotDropHandlers(node) {
    // Replace the built-in node-wide uploader, which always writes image 1.
    node.onDragOver = function (event) {
        const state = galleries.get(node), transfer = event.dataTransfer;
        const area = imageDropArea(node, event);
        const types = Array.from(transfer?.types ?? []);
        const files = Array.from(transfer?.items ?? []).some(item => item.kind === "file" &&
            (!item.type || item.type.startsWith("image/")));
        const accepted = area && !state.uploading.has(area.slot) && (files ||
            Array.from(transfer?.files ?? []).some(isImageFile) ||
            types.some(type => ["text/uri-list", "application/x-comfy-asset-info"].includes(type)));
        state.dropSlot = accepted ? area.slot : null;
        node.setDirtyCanvas(true, true);
        return !!accepted;
    };
    node.onDragDrop = async function (event) {
        const state = galleries.get(node), area = imageDropArea(node, event), transfer = event.dataTransfer;
        state.dropSlot = null;
        node.setDirtyCanvas(true, true);
        if (!area || !transfer || state.uploading.has(area.slot)) return false;
        const files = Array.from(transfer.files ?? []);
        if (files.length) {
            if (!files.every(isImageFile)) return false;
            if (files.length !== 1) app.ui.dialog.show("Drop one image into each image area.");
            else await uploadSlotFile(node, area.slot, files[0]);
            return true;
        }
        const path = droppedImagePath(transfer);
        if (!path) return false;
        setSlotImage(node, area.slot, path);
        return true;
    };
}

function addImagePreviews(node) {
    if (node.widgets?.some(w => w.name === "nodeui_slot_previews")) return;
    const cache = new Map();
    const state = {areas: [], uploading: new Set(), dropSlot: null};
    galleries.set(node, state);
    let buttons = [];
    const height = () => {
        const count = connectedImages(node).length;
        return count ? Math.ceil(count / (node.size[0] >= 300 ? 2 : 1)) * 174 + 8 : 0;
    };
    const widget = node.addCustomWidget({
        name: "nodeui_slot_previews", type: "nodeui_slot_previews",
        options: {serialize: false}, serializeValue: () => undefined,
        computeSize: width => [width, height()],
        mouse(event, pos) {
            if (!["pointerdown", "mousedown"].includes(event.type)) return false;
            const hit = buttons.find(b => pos[0] >= b.x && pos[0] <= b.x + b.w && pos[1] >= b.y && pos[1] <= b.y + 26);
            if (!hit) return false;
            if (state.uploading.has(hit.slot)) return true;
            if (hit.action === "Remove") setSlotImage(node, hit.slot, null);
            else if (hit.action === "Select") void selectSlot(node, hit.slot, event);
            else uploadSlot(node, hit.slot);
            return true;
        },
        draw(ctx, owner, width, y) {
            const slots = connectedImages(owner), paths = previewPaths(owner);
            const columns = width >= 300 ? 2 : 1, gap = 8;
            const tileWidth = (width - 24 - gap * (columns - 1)) / columns;
            const active = new Set(paths.filter(Boolean));
            for (const key of cache.keys()) if (!active.has(key)) cache.delete(key);
            buttons = [];
            state.areas = [];
            ctx.save();
            slots.forEach(({output, slot}, index) => {
                const x = 12 + (index % columns) * (tileWidth + gap);
                const top = y + Math.floor(index / columns) * 174;
                ctx.fillStyle = "#202124"; ctx.fillRect(x, top, tileWidth, 164);
                const hovered = state.dropSlot === slot && app.dragOverNode === owner;
                ctx.strokeStyle = hovered ? "#7ac6ff" : "#666";
                ctx.lineWidth = hovered ? 2 : 1; ctx.strokeRect(x, top, tileWidth, 164);
                state.areas.push({x, y: top, w: tileWidth, h: 164, slot});
                ctx.fillStyle = "#ddd"; ctx.font = "12px sans-serif"; ctx.textAlign = "left";
                ctx.fillText(output.name, x + 8, top + 18);
                const path = paths[(slot === 0 ? 1 : slot) - 1];
                let entry = path ? cache.get(path) : null;
                if (path && !entry) {
                    const match = path.match(/\s*\[(input|output|temp)\]\s*$/);
                    const clean = path.replace(/\s*\[(input|output|temp)\]\s*$/, "").replaceAll("\\", "/");
                    const parts = clean.split("/"), filename = parts.pop();
                    const image = new Image(); entry = {image, failed: false}; cache.set(path, entry);
                    image.onload = () => owner.setDirtyCanvas(true, true);
                    image.onerror = () => { entry.failed = true; owner.setDirtyCanvas(true, true); };
                    image.src = api.apiURL("/view?" + new URLSearchParams({filename, subfolder: parts.join("/"), type: match?.[1] || "input"}));
                }
                if (state.uploading.has(slot)) {
                    ctx.fillStyle = "#aaa"; ctx.textAlign = "center";
                    ctx.fillText("Uploading…", x + tileWidth / 2, top + 78);
                } else if (entry?.image.complete && entry.image.naturalWidth) {
                    const image = entry.image, scale = Math.min((tileWidth - 16) / image.naturalWidth, 98 / image.naturalHeight);
                    const w = image.naturalWidth * scale, h = image.naturalHeight * scale;
                    ctx.drawImage(image, x + (tileWidth - w) / 2, top + 26 + (98 - h) / 2, w, h);
                } else {
                    ctx.fillStyle = "#aaa"; ctx.textAlign = "center";
                    ctx.fillText(!path ? "No image supplied" : entry?.failed ? "Preview unavailable" : "Loading…", x + tileWidth / 2, top + 78);
                }
                for (const [index, action] of ["Upload", "Select", "Remove"].entries()) {
                    const bw = (tileWidth - 20) / 3, bx = x + 6 + index * (bw + 4);
                    ctx.fillStyle = state.uploading.has(slot) ? "#303236" : "#42454a";
                    ctx.fillRect(bx, top + 132, bw, 26);
                    ctx.fillStyle = "#fff"; ctx.textAlign = "center";
                    ctx.fillText(action, bx + bw / 2, top + 149, bw - 6);
                    buttons.push({x:bx, y:top+132, w:bw, slot, action});
                }
            });
            ctx.restore();
        },
    });
    // Explicit layout bounds prevent LegacyWidget from retaining a stale image-preview height.
    widget.computeLayoutSize = () => ({minWidth:160, minHeight:height(), maxHeight:height()});
}

function positionOutputs(node) {
    const height = LiteGraph.NODE_SLOT_HEIGHT;
    const x = node.size[0] + 1 - height / 2;
    for (const [index, output] of (node.outputs ?? []).entries()) {
        // Presentation order differs from the stable image/prompt socket indices.
        const row = index === 1 ? 0 : index === 0 ? 1 : index;
        const y = (row + 0.7) * height + (node.constructor.slot_start_y || 0);
        if (output.pos?.[0] !== x || output.pos?.[1] !== y) output.pos = [x, y];
    }
}

function growImageOutputs(node) {
    const outputs = node.outputs ?? [];
    for (let i = 0; i < outputs.length; i++) {
        outputs[i].name = i === 1 ? "prompt" : `image ${i === 0 ? 1 : i}`;
    }
    const last = outputs.length === 2 ? 0 : outputs.length - 1;
    if (node.isOutputConnected?.(last) ?? outputs[last]?.links?.length) {
        node.addOutput(`image ${outputs.length}`, "IMAGE");
        const size = node.computeSize();
        node.setSize([Math.max(node.size[0], size[0]), Math.max(node.size[1], size[1])]);
    }
    for (const widget of node.widgets ?? []) {
        if (["image", "image_paths", "upload"].includes(widget.name)) {
            widget.hidden = true;
            widget.computeSize = () => [0, -4];
            widget.computeLayoutSize = () => ({minWidth:0, minHeight:0, maxHeight:0});
        }
        if (widget.name === "prompt") {
            widget.computeSize = width => [width, 64];
            widget.computeLayoutSize = () => ({minWidth:160, minHeight:64, maxHeight:64});
        }
        if (widget.name === "image_paths") widget.serializeValue = () => {
            const images = previewPaths(node);
            return images.length > 1 || !images[0] ? JSON.stringify(images) : "";
        };
    }
    positionOutputs(node);
    addImagePreviews(node);
    const size = node.computeSize();
    if (Math.abs(node.size[1] - size[1]) > 1) node.setSize([node.size[0], size[1]]);
    node.setDirtyCanvas(true, true);
}

app.registerExtension({
    name: "NodeUI.SharedInputImages",
    nodeCreated(node) {
        if (node.comfyClass === "NodeUISharedInput") addSlotDropHandlers(node);
    },
    beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "NodeUISharedInput") return;
        const created = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function (...args) {
            const result = created?.apply(this, args);
            growImageOutputs(this);
            return result;
        };
        const changed = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function (...args) {
            const result = changed?.apply(this, args);
            // Graph configuration restores saved slots and links in several steps.
            if (!app.configuringGraph) growImageOutputs(this);
            return result;
        };
        nodeType.prototype.onResize = function (...args) {
            positionOutputs(this);
        };
        // Replace ComfyUI's single-image preview with the per-output gallery.
        nodeType.prototype.onDrawBackground = function () {
            for (let i = (this.widgets?.length ?? 0) - 1; i >= 0; i--) {
                if (this.widgets[i].type === "IMAGE_PREVIEW") {
                    this.widgets[i].onRemove?.(); this.widgets.splice(i, 1);
                }
            }
        };
    },
    loadedGraphNode(node) {
        if (node.comfyClass === "NodeUISharedInput") growImageOutputs(node);
    },
    afterConfigureGraph() {
        for (const node of app.graph?.nodes ?? []) {
            if (node.comfyClass === "NodeUISharedInput") growImageOutputs(node);
        }
    },
});
