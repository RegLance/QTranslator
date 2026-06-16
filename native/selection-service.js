/**
 * Selection Service - 文本选择监控服务
 * 
 * 功能：监听全局文本选择事件，通过 stdout 输出 JSON 格式的选择信息
 * 输出格式：{"text": "选中的文本", "x": 100, "y": 200, "program": "程序名"}
 * 
 * 使用方式：node selection-service.js
 * 黑名单：启动时读环境变量 QTRANSLATOR_BLACKLIST（JSON 数组）；运行中可通过 stdin 热更新。
 */

const SelectionHook = require('selection-hook');
const readline = require('readline');

// 创建选择钩子实例
const selectionHook = new SelectionHook();

// Cherry Studio 同款：部分软件需要特殊处理剪贴板兜底。
const EXCLUDE_CLIPBOARD_CURSOR_DETECT = [
    'acrobat.exe',
    'acrord32.exe',
    'acrord64.exe',
    'wps.exe',
    'cajviewer.exe',
];

const INCLUDE_CLIPBOARD_DELAY_READ = [
    'acrobat.exe',
    'acrord32.exe',
    'acrord64.exe',
    'wps.exe',
    'cajviewer.exe',
    'foxitphantom.exe',
    'foxitreader.exe',
];

// 防抖控制
let lastText = '';
let lastTime = 0;
const DEBOUNCE_MS = 100;

/** @type {string[]} */
let activeBlacklist = [];

function normalizeProgramList(programs) {
    if (!Array.isArray(programs)) {
        return [];
    }
    return programs
        .map((p) => String(p || '').trim().toLowerCase())
        .filter(Boolean);
}

function readInitialBlacklistFromEnv() {
    const raw = process.env.QTRANSLATOR_BLACKLIST;
    if (!raw) {
        return [];
    }
    try {
        return normalizeProgramList(JSON.parse(raw));
    } catch (_err) {
        return [];
    }
}

function applyBlacklist(programs) {
    activeBlacklist = normalizeProgramList(programs);

    if (!SelectionHook.FilterMode) {
        return true;
    }

    if (activeBlacklist.length === 0) {
        selectionHook.setGlobalFilterMode(SelectionHook.FilterMode.DEFAULT, []);
    } else {
        selectionHook.setGlobalFilterMode(
            SelectionHook.FilterMode.EXCLUDE_LIST,
            activeBlacklist,
        );
    }
    return true;
}

function pointOrNull(point) {
    if (!point || point.x === SelectionHook.INVALID_COORDINATE || point.y === SelectionHook.INVALID_COORDINATE) {
        return null;
    }
    return point;
}

function getSelectionPosition(data) {
    const posLevel = data.posLevel;

    if (posLevel === SelectionHook.PositionLevel.MOUSE_SINGLE) {
        const mouseEnd = pointOrNull(data.mousePosEnd);
        if (mouseEnd) {
            return { x: mouseEnd.x, y: mouseEnd.y + 16 };
        }
    }

    if (posLevel === SelectionHook.PositionLevel.MOUSE_DUAL) {
        const mouseStart = pointOrNull(data.mousePosStart);
        const mouseEnd = pointOrNull(data.mousePosEnd);
        if (mouseStart && mouseEnd) {
            const yDistance = mouseEnd.y - mouseStart.y;
            if (Math.abs(yDistance) > 14) {
                return {
                    x: mouseEnd.x,
                    y: mouseEnd.y + (yDistance > 0 ? 16 : -16),
                };
            }
            return {
                x: mouseEnd.x,
                y: Math.max(mouseEnd.y, mouseStart.y) + 16,
            };
        }
    }

    if (posLevel === SelectionHook.PositionLevel.SEL_FULL || posLevel === SelectionHook.PositionLevel.SEL_DETAILED) {
        const endBottom = pointOrNull(data.endBottom);
        const startBottom = pointOrNull(data.startBottom);
        const mouseStart = pointOrNull(data.mousePosStart);
        const mouseEnd = pointOrNull(data.mousePosEnd);

        if (mouseStart && mouseEnd && startBottom && endBottom) {
            const isSameLine = startBottom.y === endBottom.y;
            if (isSameLine && mouseEnd.x < mouseStart.x) {
                return { x: startBottom.x, y: startBottom.y + 4 };
            }
        }

        if (endBottom) {
            return { x: endBottom.x, y: endBottom.y + 4 };
        }
    }

    const mouseEnd = pointOrNull(data.mousePosEnd);
    if (mouseEnd) {
        return mouseEnd;
    }

    const endBottom = pointOrNull(data.endBottom);
    if (endBottom) {
        return { x: endBottom.x, y: endBottom.y + 4 };
    }

    return { x: 0, y: 0 };
}

function configureSelectionHook() {
    if (SelectionHook.FineTunedListType) {
        selectionHook.setFineTunedList(
            SelectionHook.FineTunedListType.EXCLUDE_CLIPBOARD_CURSOR_DETECT,
            EXCLUDE_CLIPBOARD_CURSOR_DETECT,
        );
        selectionHook.setFineTunedList(
            SelectionHook.FineTunedListType.INCLUDE_CLIPBOARD_DELAY_READ,
            INCLUDE_CLIPBOARD_DELAY_READ,
        );
    }

    applyBlacklist(readInitialBlacklistFromEnv());
}

// 监听文本选择事件
selectionHook.on('text-selection', (data) => {
    const now = Date.now();
    
    // 防抖：相同文本在短时间内不重复输出
    if (data.text === lastText && now - lastTime < DEBOUNCE_MS) {
        return;
    }
    
    lastText = data.text;
    lastTime = now;

    const position = getSelectionPosition(data);
    
    // 输出 JSON 到 stdout
    const result = {
        text: data.text || '',
        x: position.x || 0,
        y: position.y || 0,
        program: data.programName || '',
        method: data.method,
        posLevel: data.posLevel,
        timestamp: now
    };
    
    console.log(JSON.stringify(result));
});

function emitCurrentSelection(requestId) {
    try {
        const data = selectionHook.getCurrentSelection();
        if (!data || !data.text) {
            console.log(JSON.stringify({
                type: 'current-selection',
                requestId,
                text: '',
                x: 0,
                y: 0,
                program: '',
                method: '',
                posLevel: null,
                timestamp: Date.now(),
            }));
            return;
        }

        const position = getSelectionPosition(data);
        console.log(JSON.stringify({
            type: 'current-selection',
            requestId,
            text: data.text || '',
            x: position.x || 0,
            y: position.y || 0,
            program: data.programName || '',
            method: data.method,
            posLevel: data.posLevel,
            timestamp: Date.now(),
        }));
    } catch (err) {
        console.log(JSON.stringify({
            type: 'current-selection',
            requestId,
            text: '',
            error: err.message,
            timestamp: Date.now(),
        }));
    }
}

const rl = readline.createInterface({
    input: process.stdin,
    terminal: false,
});

rl.on('line', (line) => {
    try {
        const message = JSON.parse(line);
        if (message && message.cmd === 'get-current-selection') {
            emitCurrentSelection(message.id || null);
            return;
        }
        if (message && message.cmd === 'set-blacklist') {
            applyBlacklist(message.programs || []);
            console.log(JSON.stringify({
                type: 'blacklist-updated',
                ok: true,
                count: activeBlacklist.length,
                timestamp: Date.now(),
            }));
        }
    } catch (err) {
        console.error(JSON.stringify({ error: err.message }));
    }
});

// 监听错误
selectionHook.on('error', (err) => {
    console.error(JSON.stringify({ error: err.message }));
});

// 启动监控：启用剪贴板回退（无障碍取不到文本时的最后手段，会模拟复制）。
try {
    configureSelectionHook();
    selectionHook.start({ enableClipboard: true });
    // 输出就绪信号
    console.log(JSON.stringify({ ready: true }));
} catch (err) {
    console.error(JSON.stringify({ error: err.message }));
    process.exit(1);
}

// 优雅退出
process.on('SIGINT', () => {
    selectionHook.stop();
    selectionHook.cleanup();
    process.exit(0);
});

process.on('SIGTERM', () => {
    selectionHook.stop();
    selectionHook.cleanup();
    process.exit(0);
});
