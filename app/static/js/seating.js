(function () {
    const canvas = document.getElementById('seating-canvas');
    if (!canvas) return;

    const cfg = window.SEATING_CONFIG || {};
    const token = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
    const headers = {
        'Content-Type': 'application/json',
        ...(token ? {'X-CSRFToken': token, 'X-CSRF-Token': token} : {})
    };

    const layoutSelect = document.getElementById('layoutSelect');
    const layoutNameInput = document.getElementById('layoutName');

    let drag = null;

    function getCardPosition(card) {
        return {
            x: parseFloat(card.style.left) || 0,
            y: parseFloat(card.style.top) || 0,
            locked: card.dataset.locked === 'true',
            userId: parseInt(card.dataset.userId, 10)
        };
    }

    function updateScoreVisuals(card, total) {
        const nameEl = card.querySelector('.name');
        if (!nameEl) return;
        nameEl.classList.remove('pos', 'neg');
        if (total > 0) nameEl.classList.add('pos');
        if (total < 0) nameEl.classList.add('neg');
    }

    async function apiPost(url, body) {
        const resp = await fetch(url, {method: 'POST', headers, body: JSON.stringify(body || {})});
        const payload = await resp.json().catch(() => ({}));
        if (!resp.ok || payload.ok === false) {
            throw new Error(payload.error || `Request failed (${resp.status})`);
        }
        return payload;
    }

    function applyPositions(positions) {
        const byId = new Map((positions || []).map(p => [String(p.user_id), p]));
        document.querySelectorAll('.seat-card').forEach((card) => {
            const p = byId.get(card.dataset.userId);
            if (!p) return;
            card.style.left = `${parseFloat(p.x) || 0}px`;
            card.style.top = `${parseFloat(p.y) || 0}px`;
            const isLocked = !!p.locked;
            card.dataset.locked = isLocked ? 'true' : 'false';
            const icon = card.querySelector('.lock-btn i');
            if (icon) icon.className = isLocked ? 'fa fa-lock' : 'fa fa-unlock';
        });
    }

    async function savePosition(card, extra = {}) {
        const pos = getCardPosition(card);
        const url = `${cfg.seatingUpdateBase}${pos.userId}`;
        await apiPost(url, {x: pos.x, y: pos.y, ...extra});
    }

    function onPointerDown(e) {
        const card = e.target.closest('.seat-card');
        if (!card || e.target.closest('.btn') || card.dataset.locked === 'true') return;

        const cardRect = card.getBoundingClientRect();
        drag = {
            id: e.pointerId,
            card,
            dx: e.clientX - cardRect.left,
            dy: e.clientY - cardRect.top
        };

        try {
            card.setPointerCapture(e.pointerId);
        } catch (err) {
            console.debug('pointer capture not available', err);
        }
        card.classList.add('dragging');
        e.preventDefault();
    }

    function onPointerMove(e) {
        if (!drag || e.pointerId !== drag.id) return;
        const rect = canvas.getBoundingClientRect();

        let x = e.clientX - rect.left - drag.dx;
        let y = e.clientY - rect.top - drag.dy;
        x = Math.max(0, Math.min(x, rect.width - drag.card.offsetWidth));
        y = Math.max(0, Math.min(y, rect.height - drag.card.offsetHeight));

        drag.card.style.left = `${x}px`;
        drag.card.style.top = `${y}px`;
    }

    async function onPointerUp(e) {
        if (!drag || e.pointerId !== drag.id) return;
        const card = drag.card;
        drag = null;
        card.classList.remove('dragging');
        try {
            await savePosition(card, {drag: true});
        } catch (err) {
            console.error('Failed to save dragged position', err);
        }
    }

    async function refreshLayouts() {
        if (!layoutSelect || !cfg.layoutsListUrl) return;
        try {
            const resp = await fetch(cfg.layoutsListUrl, {headers});
            const layouts = await resp.json();
            if (!Array.isArray(layouts)) return;

            const previous = layoutSelect.value;
            layoutSelect.innerHTML = '<option value="">Select saved layout…</option>';
            layouts.forEach((layout) => {
                const opt = document.createElement('option');
                opt.value = String(layout.id);
                opt.textContent = layout.name;
                layoutSelect.appendChild(opt);
            });
            if (previous) layoutSelect.value = previous;
        } catch (err) {
            console.error('Failed to load layouts', err);
        }
    }

    async function handleSaveLayout() {
        const rawName = (layoutNameInput?.value || '').trim();
        const selectedName = layoutSelect?.selectedOptions?.[0]?.text || '';
        const name = rawName || selectedName;
        if (!name) {
            alert('Enter a layout name first.');
            return;
        }

        let overwrite = false;
        if (!rawName && layoutSelect?.value) {
            overwrite = confirm(`Overwrite existing layout "${selectedName}"?`);
            if (!overwrite) return;
        }

        try {
            await apiPost(cfg.layoutsSaveUrl, {name, overwrite});
            if (layoutNameInput) layoutNameInput.value = '';
            await refreshLayouts();
            const matching = Array.from(layoutSelect?.options || []).find(o => o.text === name);
            if (matching) layoutSelect.value = matching.value;
            alert(`Layout "${name}" saved.`);
        } catch (err) {
            alert(err.message || 'Unable to save layout.');
        }
    }

    async function handleLoadLayout() {
        const id = layoutSelect?.value;
        if (!id) {
            alert('Select a layout to load.');
            return;
        }

        try {
            const payload = await apiPost(`${cfg.layoutsLoadBase}${id}/load`, {});
            applyPositions(payload.positions || []);
        } catch (err) {
            alert(err.message || 'Unable to load layout.');
        }
    }

    canvas.addEventListener('pointerdown', onPointerDown);
    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', onPointerUp);

    canvas.addEventListener('click', async (e) => {
        const lockBtn = e.target.closest('.lock-btn');
        if (lockBtn) {
            const card = lockBtn.closest('.seat-card');
            const newLocked = !(card.dataset.locked === 'true');
            card.dataset.locked = newLocked ? 'true' : 'false';
            lockBtn.querySelector('i').className = newLocked ? 'fa fa-lock' : 'fa fa-unlock';
            try {
                await savePosition(card, {locked: newLocked});
            } catch (err) {
                console.error('Failed to save lock status', err);
            }
            return;
        }

        const behaviourBtn = e.target.closest('.behaviour-plus, .behaviour-minus');
        if (!behaviourBtn) return;

        const delta = parseInt(behaviourBtn.dataset.delta, 10);
        const card = behaviourBtn.closest('.seat-card');
        const userId = card.dataset.userId;

        try {
            const payload = await apiPost(`${cfg.behaviourAdjustBase}${userId}/adjust`, {delta});
            const total = parseInt(payload.total, 10) || 0;
            const totalEl = card.querySelector('.behaviour-total');
            totalEl.textContent = String(total);
            updateScoreVisuals(card, total);
        } catch (err) {
            console.error('Behaviour update failed', err);
        }
    });

    async function bulkLock(flag) {
        document.querySelectorAll('.seat-card').forEach((card) => {
            card.dataset.locked = flag ? 'true' : 'false';
            const icon = card.querySelector('.lock-btn i');
            if (icon) icon.className = flag ? 'fa fa-lock' : 'fa fa-unlock';
        });

        try {
            await apiPost(`/courses/${cfg.courseId}/api/seating/bulk_lock`, {locked: flag});
        } catch (err) {
            console.error('Bulk lock failed', err);
        }
    }

    document.getElementById('lockAll')?.addEventListener('click', () => bulkLock(true));
    document.getElementById('unlockAll')?.addEventListener('click', () => bulkLock(false));

    document.getElementById('resetLayout')?.addEventListener('click', () => {
        document.querySelectorAll('.seat-card').forEach((card, idx) => {
            card.style.left = `${idx * 16}px`;
            card.style.top = `${idx * 16}px`;
            card.dataset.locked = 'false';
            const icon = card.querySelector('.lock-btn i');
            if (icon) icon.className = 'fa fa-unlock';
            savePosition(card, {locked: false}).catch((err) => console.error('Reset save failed', err));
        });
    });

    document.addEventListener('visibilitychange', () => {
        if (drag) {
            savePosition(drag.card, {drag: true}).catch((err) => console.error('Visibility save failed', err));
        }
    });

    document.querySelectorAll('.seat-card').forEach((card) => {
        const el = card.querySelector('.behaviour-total');
        const initial = parseInt(el?.getAttribute('data-initial') || el?.textContent || '0', 10) || 0;
        updateScoreVisuals(card, initial);
    });

    document.getElementById('saveLayout')?.addEventListener('click', handleSaveLayout);
    document.getElementById('loadLayout')?.addEventListener('click', handleLoadLayout);

    refreshLayouts();
})();
