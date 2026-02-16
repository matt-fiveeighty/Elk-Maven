// Canvas markup — draw annotations on uploaded images
'use strict';

let canvasState = {
    imageId: null,
    tool: 'pen',
    color: '#ff0000',
    lineWidth: 3,
    isDrawing: false,
    startX: 0,
    startY: 0,
    annotations: [],
    undoStack: [],
    backgroundImage: null,
};

// Open markup modal for an image
function openMarkup(imageId) {
    canvasState.imageId = imageId;
    canvasState.annotations = [];
    canvasState.undoStack = [];

    const modal = document.getElementById('canvasModal');
    modal.style.display = 'flex';

    const canvas = document.getElementById('markupCanvas');
    const ctx = canvas.getContext('2d');

    // Load image
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => {
        // Scale to fit viewport
        const maxW = window.innerWidth * 0.9;
        const maxH = window.innerHeight * 0.85;
        let w = img.width;
        let h = img.height;

        if (w > maxW) { h = h * maxW / w; w = maxW; }
        if (h > maxH) { w = w * maxH / h; h = maxH; }

        canvas.width = Math.round(w);
        canvas.height = Math.round(h);
        canvasState.backgroundImage = img;

        redrawCanvas();

        // Load existing markup
        fetch(`/api/images/${imageId}/markup`)
            .then(r => r.json())
            .then(data => {
                if (data.markup_data && data.markup_data.annotations) {
                    canvasState.annotations = data.markup_data.annotations;
                    redrawCanvas();
                }
            })
            .catch(() => {});
    };
    img.src = `/api/images/${imageId}`;

    // Set up event listeners
    setupCanvasEvents(canvas);
    setupToolbar();
}

function setupCanvasEvents(canvas) {
    // Remove old listeners by cloning
    const newCanvas = canvas.cloneNode(true);
    canvas.parentNode.replaceChild(newCanvas, canvas);
    const ctx = newCanvas.getContext('2d');

    newCanvas.addEventListener('mousedown', (e) => {
        const rect = newCanvas.getBoundingClientRect();
        canvasState.isDrawing = true;
        canvasState.startX = e.clientX - rect.left;
        canvasState.startY = e.clientY - rect.top;

        if (canvasState.tool === 'pen') {
            canvasState.currentPath = [{
                x: canvasState.startX,
                y: canvasState.startY,
            }];
        }

        if (canvasState.tool === 'text') {
            const text = prompt('Enter label text:');
            if (text) {
                canvasState.annotations.push({
                    type: 'text',
                    x: canvasState.startX,
                    y: canvasState.startY,
                    text: text,
                    color: canvasState.color,
                    fontSize: 16,
                });
                redrawCanvas();
            }
            canvasState.isDrawing = false;
        }
    });

    newCanvas.addEventListener('mousemove', (e) => {
        if (!canvasState.isDrawing) return;
        const rect = newCanvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;

        if (canvasState.tool === 'pen') {
            canvasState.currentPath.push({ x, y });
            // Draw preview
            redrawCanvas();
            ctx.beginPath();
            ctx.strokeStyle = canvasState.color;
            ctx.lineWidth = canvasState.lineWidth;
            ctx.lineCap = 'round';
            ctx.lineJoin = 'round';
            const path = canvasState.currentPath;
            ctx.moveTo(path[0].x, path[0].y);
            for (let i = 1; i < path.length; i++) {
                ctx.lineTo(path[i].x, path[i].y);
            }
            ctx.stroke();
        } else if (canvasState.tool === 'line' || canvasState.tool === 'arrow') {
            redrawCanvas();
            drawLine(ctx, canvasState.startX, canvasState.startY, x, y,
                     canvasState.color, canvasState.lineWidth,
                     canvasState.tool === 'arrow');
        } else if (canvasState.tool === 'rect') {
            redrawCanvas();
            drawRect(ctx, canvasState.startX, canvasState.startY, x, y,
                     canvasState.color, canvasState.lineWidth);
        }
    });

    newCanvas.addEventListener('mouseup', (e) => {
        if (!canvasState.isDrawing) return;
        canvasState.isDrawing = false;

        const rect = newCanvas.getBoundingClientRect();
        const endX = e.clientX - rect.left;
        const endY = e.clientY - rect.top;

        if (canvasState.tool === 'pen' && canvasState.currentPath) {
            canvasState.annotations.push({
                type: 'freehand',
                points: canvasState.currentPath,
                color: canvasState.color,
                width: canvasState.lineWidth,
            });
            canvasState.currentPath = null;
        } else if (canvasState.tool === 'line') {
            canvasState.annotations.push({
                type: 'line',
                x1: canvasState.startX, y1: canvasState.startY,
                x2: endX, y2: endY,
                color: canvasState.color, width: canvasState.lineWidth,
            });
        } else if (canvasState.tool === 'arrow') {
            canvasState.annotations.push({
                type: 'arrow',
                x1: canvasState.startX, y1: canvasState.startY,
                x2: endX, y2: endY,
                color: canvasState.color, width: canvasState.lineWidth,
            });
        } else if (canvasState.tool === 'rect') {
            canvasState.annotations.push({
                type: 'rect',
                x: canvasState.startX, y: canvasState.startY,
                w: endX - canvasState.startX, h: endY - canvasState.startY,
                color: canvasState.color, width: canvasState.lineWidth,
            });
        }

        redrawCanvas();
    });
}

function setupToolbar() {
    // Tool buttons
    document.querySelectorAll('.tool-btn[data-tool]').forEach(btn => {
        btn.onclick = () => {
            document.querySelectorAll('.tool-btn[data-tool]').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            canvasState.tool = btn.dataset.tool;
        };
    });

    // Color buttons
    document.querySelectorAll('.color-btn').forEach(btn => {
        btn.onclick = () => {
            document.querySelectorAll('.color-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            canvasState.color = btn.dataset.color;
        };
    });

    // Undo
    document.getElementById('undoBtn').onclick = () => {
        if (canvasState.annotations.length) {
            canvasState.undoStack.push(canvasState.annotations.pop());
            redrawCanvas();
        }
    };

    // Clear
    document.getElementById('clearBtn').onclick = () => {
        if (confirm('Clear all annotations?')) {
            canvasState.undoStack = canvasState.annotations.slice();
            canvasState.annotations = [];
            redrawCanvas();
        }
    };

    // Save
    document.getElementById('saveMarkupBtn').onclick = saveMarkup;

    // Close
    document.getElementById('closeCanvasBtn').onclick = () => {
        document.getElementById('canvasModal').style.display = 'none';
    };
}

function redrawCanvas() {
    const canvas = document.getElementById('markupCanvas');
    const ctx = canvas.getContext('2d');

    // Draw background image
    if (canvasState.backgroundImage) {
        ctx.drawImage(canvasState.backgroundImage, 0, 0, canvas.width, canvas.height);
    } else {
        ctx.fillStyle = '#333';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
    }

    // Draw all annotations
    canvasState.annotations.forEach(ann => {
        switch (ann.type) {
            case 'freehand':
                ctx.beginPath();
                ctx.strokeStyle = ann.color;
                ctx.lineWidth = ann.width;
                ctx.lineCap = 'round';
                ctx.lineJoin = 'round';
                if (ann.points.length > 0) {
                    ctx.moveTo(ann.points[0].x, ann.points[0].y);
                    for (let i = 1; i < ann.points.length; i++) {
                        ctx.lineTo(ann.points[i].x, ann.points[i].y);
                    }
                }
                ctx.stroke();
                break;
            case 'line':
                drawLine(ctx, ann.x1, ann.y1, ann.x2, ann.y2, ann.color, ann.width, false);
                break;
            case 'arrow':
                drawLine(ctx, ann.x1, ann.y1, ann.x2, ann.y2, ann.color, ann.width, true);
                break;
            case 'rect':
                drawRect(ctx, ann.x, ann.y, ann.x + ann.w, ann.y + ann.h, ann.color, ann.width);
                break;
            case 'text':
                ctx.font = `bold ${ann.fontSize || 16}px sans-serif`;
                ctx.fillStyle = ann.color;
                // Text shadow for visibility
                ctx.shadowColor = 'rgba(0,0,0,0.7)';
                ctx.shadowBlur = 4;
                ctx.fillText(ann.text, ann.x, ann.y);
                ctx.shadowBlur = 0;
                break;
        }
    });
}

function drawLine(ctx, x1, y1, x2, y2, color, width, withArrow) {
    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.lineCap = 'round';
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.stroke();

    if (withArrow) {
        const angle = Math.atan2(y2 - y1, x2 - x1);
        const headLen = 15;
        ctx.beginPath();
        ctx.fillStyle = color;
        ctx.moveTo(x2, y2);
        ctx.lineTo(
            x2 - headLen * Math.cos(angle - Math.PI / 6),
            y2 - headLen * Math.sin(angle - Math.PI / 6)
        );
        ctx.lineTo(
            x2 - headLen * Math.cos(angle + Math.PI / 6),
            y2 - headLen * Math.sin(angle + Math.PI / 6)
        );
        ctx.closePath();
        ctx.fill();
    }
}

function drawRect(ctx, x1, y1, x2, y2, color, width) {
    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.rect(x1, y1, x2 - x1, y2 - y1);
    ctx.stroke();
}

async function saveMarkup() {
    if (!canvasState.imageId) return;

    try {
        await fetch(`/api/images/${canvasState.imageId}/markup`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                markup_data: {
                    annotations: canvasState.annotations,
                    version: 1,
                },
            }),
        });
        // Close modal
        document.getElementById('canvasModal').style.display = 'none';
    } catch (e) {
        console.error('Failed to save markup:', e);
        alert('Failed to save markup');
    }
}
