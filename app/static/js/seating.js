(function () {
    const canvas = document.getElementById('seating-canvas');
    if (!canvas) return;

    const cfg = window.SEATING_CONFIG || {};
    const courseId = cfg.courseId;
    const token = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
    const headers = {
        'Content-Type': 'application/json',
        ...(token ? {'X-CSRFToken': token, 'X-CSRF-Token': token} : {}) // both header names
    };

    let drag = null;

    async function savePosition(card, extra = {}) {
        const x = parseFloat(card.style.left) || 0;
        const y = parseFloat(card.style.top) || 0;
        const userId = card.dataset.userId;
        const url = `${cfg.seatingUpdateBase}${userId}`;   // <-- use base from template
        try {
            const resp = await fetch(url, {
                method: 'POST',
                headers,
                body: JSON.stringify({x, y, ...extra})
            });
            if (!resp.ok) {
                console.error('savePosition failed', resp.status, await resp.text());
            }
        } catch (err) {
            console.error('savePosition failed', err);
        }
    }

    function onPointerDown(e) {
        const card = e.target.closest('.seat-card');
        if (!card) return;
        if (e.target.closest('.btn')) return;           // ignore button presses
        if (card.dataset.locked === 'true') return;

        const canvasRect = canvas.getBoundingClientRect();
        const cardRect = card.getBoundingClientRect();

        drag = {
            id: e.pointerId,
            card,
            dx: e.clientX - cardRect.left,                // pointer offset inside the card
            dy: e.clientY - cardRect.top,
            moved: false
        };

        // capture pointer so we ALWAYS receive move/up, even outside the canvas
        try {
            card.setPointerCapture(e.pointerId);
        } catch {
        }
        card.classList.add('dragging');
        e.preventDefault();
    }

    function onPointerMove(e) {
        if (!drag || e.pointerId !== drag.id) return;

        const rect = canvas.getBoundingClientRect();
        let x = e.clientX - rect.left - drag.dx;
        let y = e.clientY - rect.top - drag.dy;

        // clamp within canvas
        x = Math.max(0, Math.min(x, rect.width - drag.card.offsetWidth));
        y = Math.max(0, Math.min(y, rect.height - drag.card.offsetHeight));

        drag.card.style.left = `${x}px`;
        drag.card.style.top = `${y}px`;
        drag.moved = true;
    }

    function onPointerUp(e) {
        if (!drag || e.pointerId !== drag.id) return;
        const card = drag.card;
        drag = null;
        card.classList.remove('dragging');

        // save on drag end (even if barely moved)
        savePosition(card, {drag: true});
    }

    // Use pointer events (covers mouse + touch)
    canvas.addEventListener('pointerdown', onPointerDown);
    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', onPointerUp);

    // Lock toggle (unchanged)
    canvas.addEventListener('click', async (e) => {
        const btn = e.target.closest('.lock-btn');
        if (!btn) return;
        const card = btn.closest('.seat-card');
        const newLocked = !(card.dataset.locked === 'true');
        card.dataset.locked = newLocked ? 'true' : 'false';
        btn.querySelector('i').className = newLocked ? 'fa fa-lock' : 'fa fa-unlock';
        await fetch(`${cfg.seatingUpdateBase}${card.dataset.userId}`, {
            method: 'POST',
            headers,
            body: JSON.stringify({locked: newLocked})
        });
    });

    // Bulk lock/unlock (unchanged)
    async function bulkLock(flag) {
        document.querySelectorAll('.seat-card').forEach(c => {
            c.dataset.locked = flag ? 'true' : 'false';
            const i = c.querySelector('.lock-btn i');
            if (i) i.className = flag ? 'fa fa-lock' : 'fa fa-unlock';
        });
        await fetch(`/courses/${courseId}/api/seating/bulk_lock`, {
            method: 'POST',
            headers,
            body: JSON.stringify({locked: flag})
        });
    }

    document.getElementById('lockAll')?.addEventListener('click', () => bulkLock(true));
    document.getElementById('unlockAll')?.addEventListener('click', () => bulkLock(false));

    // Reset layout (unchanged)
    document.getElementById('resetLayout')?.addEventListener('click', () => {
        document.querySelectorAll('.seat-card').forEach((c, i) => {
            c.style.left = (i * 16) + 'px';
            c.style.top = (i * 16) + 'px';
            c.dataset.locked = 'false';
            const iNode = c.querySelector('.lock-btn i');
            if (iNode) iNode.className = 'fa fa-unlock';
            savePosition(c, {locked: false});
        });
    });

    // +/- behaviour (unchanged)
    canvas.addEventListener('click', async (e) => {
        const btn = e.target.closest('.behaviour-plus, .behaviour-minus');
        if (!btn) return;
        const delta = parseInt(btn.dataset.delta, 10);
        const card = btn.closest('.seat-card');
        const userId = card.dataset.userId;

        try {
            const resp = await fetch(`${cfg.behaviourAdjustBase}${userId}/adjust`, {
                method: 'POST',
                headers,
                body: JSON.stringify({delta})
            });
            const json = await resp.json();
            if (json && json.ok && typeof json.total !== 'undefined') {
                card.querySelector('.behaviour-total').textContent = json.total;
            } else {
                const el = card.querySelector('.behaviour-total');
                el.textContent = String((parseInt(el.textContent, 10) || 0) + delta);
            }
        } catch (err) {
            console.error('behaviour adjust failed', err);
        }
    });

    // Belt-and-braces: if tab hides mid-drag, save whatever position we have
    document.addEventListener('visibilitychange', () => {
        if (drag) {
            savePosition(drag.card, {drag: true});
        }
    });

     function updateScoreVisuals(card, total) {
    const nameEl = card.querySelector('.name');
    if (!nameEl) return;
    nameEl.classList.remove('pos', 'neg');
    if (total > 0) nameEl.classList.add('pos');
    else if (total < 0) nameEl.classList.add('neg');
  }

  // Initialize name colors from initial totals in the DOM
  document.querySelectorAll('.seat-card').forEach(card => {
    const el = card.querySelector('.behaviour-total');
    const initial = parseInt(el?.getAttribute('data-initial') || el?.textContent || '0', 10) || 0;
    updateScoreVisuals(card, initial);
  });

  // In your +/- behaviour click handler, after updating the number:
  canvas.addEventListener('click', async (e) => {
    const btn = e.target.closest('.behaviour-plus, .behaviour-minus');
    if (!btn) return;
    const delta = parseInt(btn.dataset.delta, 10);
    const card  = btn.closest('.seat-card');
    const userId = card.dataset.userId;

    try {
      const resp = await fetch(`${cfg.behaviourAdjustBase}${userId}/adjust`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ delta })
      });
      const json = await resp.json();
      let newTotal;
      if (json && json.ok && typeof json.total !== 'undefined') {
        newTotal = parseInt(json.total, 10) || 0;
        card.querySelector('.behaviour-total').textContent = newTotal;
      } else {
        const el = card.querySelector('.behaviour-total');
        newTotal = (parseInt(el.textContent, 10) || 0) + delta;
        el.textContent = newTotal;
      }
      updateScoreVisuals(card, newTotal); // <-- color name pill
    } catch (err) {
      console.error('behaviour adjust failed', err);
    }
  });
})();
