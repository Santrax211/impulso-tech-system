(() => {
  'use strict';

  /* ------------------------------------------------------------ utilidades */
  const $ = (sel, el = document) => el.querySelector(sel);
  const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];

  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else if (k === 'value') el.value = v;
      else if (v === true) el.setAttribute(k, '');
      else el.setAttribute(k, v);
    }
    for (const kid of kids.flat()) {
      if (kid === null || kid === undefined || kid === false) continue;
      el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }

  const ICONS = {
    pdf: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/><path d="M9 14h6M9 17h4"/>',
    edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/>',
    copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/>',
    trash: '<path d="M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    x: '<path d="M6 6l12 12M18 6L6 18"/>',
    receipt: '<path d="M6 3h12v18l-3-2-3 2-3-2-3 2z"/><path d="M9 8h6M9 12h6"/>',
    eye: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  };
  function icon(name) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('class', 'ico');
    svg.setAttribute('aria-hidden', 'true');
    svg.innerHTML = ICONS[name];
    return svg;
  }

  const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
  const fmtMoney = (n) => 'S/ ' + Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const num = (v) => { const n = parseFloat(String(v ?? '').replace(',', '.')); return Number.isFinite(n) && n > 0 ? n : 0; };
  const r2 = (n) => Math.round((n + Number.EPSILON) * 100) / 100;
  const pad = (n) => String(n).padStart(2, '0');
  const todayISO = () => { const d = new Date(); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };
  const fmtDate = (iso) => iso.split('-').reverse().join('/');
  const addDays = (iso, n) => {
    const [y, m, d] = iso.split('-').map(Number);
    const dt = new Date(y, m - 1, d + n);
    return `${pad(dt.getDate())}/${pad(dt.getMonth() + 1)}/${dt.getFullYear()}`;
  };

  function toast(msg, kind = 'ok') {
    const t = h('div', { class: 'toast ' + kind, role: kind === 'err' ? 'alert' : 'status' }, msg);
    $('#toasts').append(t);
    setTimeout(() => t.remove(), 4500);
  }

  function confirmDialog(message, okLabel) {
    return new Promise((resolve) => {
      const d = h('dialog', { class: 'dlg' },
        h('p', {}, message),
        h('div', { class: 'dlg-actions' },
          h('button', { class: 'btn ghost', type: 'button', onclick: () => d.close('no') }, 'Cancelar'),
          h('button', { class: 'btn danger', type: 'button', onclick: () => d.close('yes') }, okLabel)));
      d.addEventListener('close', () => { resolve(d.returnValue === 'yes'); d.remove(); });
      document.body.append(d);
      d.showModal();
    });
  }

  /* ------------------------------------------------------------ API */
  const state = { csrf: null, settings: null };

  class ApiError extends Error {
    constructor(message, status) { super(message); this.status = status; }
  }

  async function api(path, { method = 'GET', body } = {}) {
    const opts = { method, headers: {}, credentials: 'same-origin' };
    if (method !== 'GET') opts.headers['X-CSRF-Token'] = state.csrf;
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    let res;
    try { res = await fetch('/api' + path, opts); }
    catch { throw new ApiError('Sin conexión con el servidor.', 0); }
    let data = null;
    try { data = await res.json(); } catch { /* sin cuerpo */ }
    if (res.status === 401 && path !== '/login') { showLogin(); throw new ApiError('Tu sesión expiró. Ingresa de nuevo.', 401); }
    if (!res.ok) throw new ApiError((data && data.error) || 'Ocurrió un error inesperado.', res.status);
    return data;
  }

  /* ------------------------------------------------------------ sesión */
  function showLogin() {
    $('#app').hidden = true;
    $('#login').hidden = false;
    $('#view').replaceChildren();
    $('#login-form [name=password]').value = '';
    setTimeout(() => $('#login-form [name=username]').focus(), 50);
  }

  async function showApp() {
    $('#login').hidden = true;
    $('#app').hidden = false;
    state.settings = await api('/settings');
    route();
  }

  function bindLogin() {
    const form = $('#login-form');
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const err = $('#login-error');
      err.textContent = '';
      const btn = $('button[type=submit]', form);
      btn.disabled = true;
      try {
        const res = await api('/login', { method: 'POST', body: { username: form.username.value, password: form.password.value } });
        state.csrf = res.csrf;
        await showApp();
      } catch (ex) {
        err.textContent = ex.message;
      } finally { btn.disabled = false; }
    });
    $('#logout').addEventListener('click', async () => {
      try { const res = await api('/logout', { method: 'POST' }); state.csrf = res.csrf; } catch { /* ignorar */ }
      location.hash = '';
      showLogin();
    });
  }

  /* ------------------------------------------------------------ router */
  function route() {
    if ($('#app').hidden) return;
    const [, name = 'cotizaciones', id] = (location.hash || '#/cotizaciones').split('/');
    const navKey = { editar: 'cotizaciones', comprobante: 'comprobantes' }[name] || name;
    $$('[data-nav]').forEach((a) => {
      a.dataset.nav === navKey ? a.setAttribute('aria-current', 'page') : a.removeAttribute('aria-current');
    });
    const view = $('#view');
    const run = (fn) => fn().catch((e) => { if (e.status !== 401) toast(e.message, 'err'); });
    if (name === 'nueva') run(() => viewEditor(null));
    else if (name === 'editar' && /^\d+$/.test(id || '')) run(() => viewEditor(id));
    else if (name === 'comprobantes') run(viewDocs);
    else if (name === 'comprobante' && /^\d+$/.test(id || '')) run(() => viewDoc(id));
    else if (name === 'ajustes') run(viewSettings);
    else run(viewList);
    window.scrollTo(0, 0);
    view.focus({ preventScroll: true });
  }

  /* ------------------------------------------------------------ historial */
  async function viewList() {
    const view = $('#view');
    const search = h('input', { type: 'search', placeholder: 'Buscar por cliente, DNI/RUC o número', 'aria-label': 'Buscar cotizaciones' });
    const statusSel = h('select', { 'aria-label': 'Filtrar por estado' },
      h('option', { value: '' }, 'Todos los estados'),
      h('option', { value: 'enviada' }, 'Enviadas'),
      h('option', { value: 'aceptada' }, 'Aceptadas'),
      h('option', { value: 'rechazada' }, 'Rechazadas'));
    const figures = h('div', { class: 'figures' });
    const listBox = h('div');

    view.replaceChildren(
      h('div', { class: 'view-head' },
        h('h1', {}, 'Cotizaciones'),
        h('a', { class: 'btn primary', href: '#/nueva' }, icon('plus'), 'Nueva cotización')),
      figures,
      h('div', { class: 'filters' }, search, statusSel),
      listBox);

    async function load() {
      const qs = new URLSearchParams({ q: search.value, status: statusSel.value });
      const data = await api('/quotes?' + qs);
      figures.replaceChildren(
        h('div', { class: 'figure' }, h('b', {}, fmtMoney(data.stats.month_total)), h('span', {}, 'Cotizado este mes')),
        h('div', { class: 'figure' }, h('b', {}, fmtMoney(data.stats.accepted_total)), h('span', {}, 'Aceptado este mes')),
        h('div', { class: 'figure' }, h('b', {}, String(data.stats.pending)), h('span', {}, 'Esperando respuesta')));
      if (!data.quotes.length) {
        const filtering = search.value || statusSel.value;
        listBox.replaceChildren(h('div', { class: 'qlist empty' },
          h('h2', {}, filtering ? 'Sin resultados' : 'Aún no hay cotizaciones'),
          h('p', {}, filtering ? 'Prueba con otro nombre, número o estado.' : 'Crea la primera para verla aquí.'),
          filtering ? null : h('a', { class: 'btn primary', href: '#/nueva' }, 'Crear cotización')));
        return;
      }
      listBox.replaceChildren(h('div', { class: 'qlist' },
        h('div', { class: 'qhead' }, h('span', {}, 'Número'), h('span', {}, 'Cliente'), h('span', {}, 'Total'), h('span', {}, 'Estado'), h('span', {}, 'Acciones')),
        data.quotes.map(row)));
    }

    function row(q) {
      const sel = h('select', { class: 'status s-' + q.status, 'aria-label': 'Estado de ' + q.number },
        Object.entries({ enviada: 'Enviada', aceptada: 'Aceptada', rechazada: 'Rechazada' })
          .map(([v, t]) => h('option', { value: v }, t)));
      sel.value = q.status;
      sel.addEventListener('change', async () => {
        try {
          await api(`/quotes/${q.id}/status`, { method: 'PATCH', body: { status: sel.value } });
          sel.className = 'status s-' + sel.value;
          toast(`${q.number} marcada como ${sel.options[sel.selectedIndex].text.toLowerCase()}.`);
          load();
        } catch (e) { sel.value = q.status; toast(e.message, 'err'); }
      });
      return h('div', { class: 'qrow' },
        h('span', { class: 'num' }, q.number),
        h('div', { class: 'who' }, h('b', {}, q.client_name), h('small', {}, fmtDate(q.issue_date) + (q.client_doc ? ' · ' + q.client_doc : '') + (q.doc_label ? ' · ' + q.doc_label : ''))),
        h('span', { class: 'total' }, fmtMoney(q.total)),
        h('span', { class: 'st' }, sel),
        h('div', { class: 'acts' },
          h('a', { class: 'icon-btn', href: `/api/quotes/${q.id}/pdf`, target: '_blank', rel: 'noopener', title: 'Abrir PDF', 'aria-label': 'Abrir PDF de ' + q.number }, icon('pdf')),
          q.doc_id
            ? h('a', { class: 'icon-btn is-done', href: `#/comprobante/${q.doc_id}`, title: 'Ver comprobante ' + q.doc_label, 'aria-label': 'Ver comprobante ' + q.doc_label }, icon('receipt'))
            : h('button', { class: 'icon-btn', type: 'button', title: 'Registrar comprobante', 'aria-label': 'Registrar comprobante de ' + q.number, onclick: () => openEmitDialog(q) }, icon('receipt')),
          h('a', { class: 'icon-btn', href: `#/editar/${q.id}`, title: 'Editar', 'aria-label': 'Editar ' + q.number }, icon('edit')),
          h('button', {
            class: 'icon-btn', type: 'button', title: 'Duplicar', 'aria-label': 'Duplicar ' + q.number,
            onclick: async () => {
              try { const d = await api(`/quotes/${q.id}/duplicate`, { method: 'POST' }); toast(`Creada ${d.number} a partir de ${q.number}.`); location.hash = `#/editar/${d.id}`; }
              catch (e) { toast(e.message, 'err'); }
            },
          }, icon('copy')),
          h('button', {
            class: 'icon-btn del', type: 'button', title: 'Eliminar', 'aria-label': 'Eliminar ' + q.number,
            onclick: async () => {
              if (!(await confirmDialog(`¿Eliminar ${q.number} de ${q.client_name}? No se puede deshacer.`, 'Eliminar'))) return;
              try { await api('/quotes/' + q.id, { method: 'DELETE' }); toast(q.number + ' eliminada.'); load(); }
              catch (e) { toast(e.message, 'err'); }
            },
          }, icon('trash'))));
    }

    search.addEventListener('input', debounce(() => load().catch((e) => toast(e.message, 'err')), 250));
    statusSel.addEventListener('change', () => load().catch((e) => toast(e.message, 'err')));
    await load();
  }

  /* ------------------------------------------------------------ editor */
  const SERVICES = [
    ['Página web', 'Diseño y desarrollo de página web'],
    ['Landing page', 'Diseño de landing page'],
    ['Logotipo', 'Diseño de logotipo'],
    ['Excel y dashboards', 'Excel avanzado y dashboard'],
    ['Plantilla Excel', 'Plantilla automatizada en Excel'],
    ['Edición de documentos', 'Corrección y edición de documentos'],
    ['Software', 'Programación y desarrollo de software'],
    ['Mantenimiento web', 'Mantenimiento y soporte web (mensual)'],
  ];
  const IGV = 0.18;

  function calc(q) {
    const items = q.items.map((i) => r2(num(i.qty) * num(i.price)));
    const subtotal = r2(items.reduce((a, b) => a + b, 0));
    let disc = 0;
    if (q.discount_type === 'percent') disc = r2(subtotal * Math.min(num(q.discount_value), 100) / 100);
    else if (q.discount_type === 'amount') disc = r2(num(q.discount_value));
    disc = Math.min(disc, subtotal);
    const net = r2(subtotal - disc);
    let base = net, igv = 0, total = net;
    if (q.igv_mode === 'add') { igv = r2(net * IGV); total = r2(net + igv); }
    else if (q.igv_mode === 'included') { base = r2(net / (1 + IGV)); igv = r2(net - base); }
    return { items, subtotal, disc, base, igv, total };
  }

  function blankQuote() {
    return {
      client_name: '', client_doc: '', client_phone: '',
      items: [{ desc: '', qty: '1', price: '' }],
      discount_type: 'none', discount_value: '', igv_mode: 'none',
      valid_days: parseInt(state.settings.default_valid_days, 10) || 7,
      issue_date: todayISO(), conditions: state.settings.default_conditions || '', status: 'enviada',
    };
  }

  function autosize(ta) { ta.style.height = 'auto'; ta.style.height = Math.max(ta.scrollHeight + 2, 64) + 'px'; }

  async function viewEditor(id) {
    const q = id ? await api('/quotes/' + id) : blankQuote();
    if (id) {
      q.items = q.items.map((i) => ({ desc: i.desc, qty: String(parseFloat(i.qty)), price: i.price }));
      q.discount_value = q.discount_type === 'none' ? '' : String(parseFloat(q.discount_value));
    }
    const view = $('#view');
    const bind = (el, key) => { el.addEventListener('input', () => { q[key] = el.value; recalc(); }); return el; };

    const title = h('h1', {}, q.number || 'Nueva cotización');
    const name = bind(h('input', { type: 'text', value: q.client_name, maxlength: 120, autocomplete: 'off', required: true }), 'client_name');
    const doc = bind(h('input', { type: 'text', value: q.client_doc, inputmode: 'numeric', maxlength: 11, autocomplete: 'off' }), 'client_doc');
    const phone = bind(h('input', { type: 'tel', value: q.client_phone, maxlength: 30, autocomplete: 'off' }), 'client_phone');

    /* Ítems */
    const itemsBox = h('div', { class: 'items' });
    const amountEls = [];
    function renderItems() {
      amountEls.length = 0;
      itemsBox.replaceChildren(h('div', { class: 'items-head', 'aria-hidden': 'true' },
        h('span', {}, 'Descripción'), h('span', {}, 'Cant.'), h('span', {}, 'Precio unit. (S/)'), h('span', {}, 'Importe'), h('span', {})));
      q.items.forEach((it, idx) => {
        const desc = h('textarea', { rows: 2, maxlength: 2000, 'aria-label': `Descripción del servicio ${idx + 1}`, placeholder: 'Qué incluye, entregables, plazo…' });
        desc.value = it.desc;
        desc.addEventListener('input', () => { it.desc = desc.value; autosize(desc); });
        const qty = h('input', { class: 'num', type: 'text', inputmode: 'decimal', value: it.qty, 'aria-label': `Cantidad ${idx + 1}` });
        qty.addEventListener('input', () => { it.qty = qty.value; recalc(); });
        const price = h('input', { class: 'num', type: 'text', inputmode: 'decimal', value: it.price, placeholder: '0.00', 'aria-label': `Precio unitario ${idx + 1}` });
        price.addEventListener('input', () => { it.price = price.value; recalc(); });
        const out = h('output', {}, 'S/ 0.00');
        amountEls.push(out);
        itemsBox.append(h('div', { class: 'item' },
          h('div', { class: 'f-desc' }, h('span', { class: 'mini' }, 'Descripción'), desc),
          h('div', {}, h('span', { class: 'mini' }, 'Cantidad'), qty),
          h('div', {}, h('span', { class: 'mini' }, 'Precio unit. (S/)'), price),
          h('div', { class: 'f-amount' }, h('span', { class: 'mini' }, 'Importe'), out),
          h('button', {
            class: 'icon-btn del f-del', type: 'button', title: 'Quitar servicio', 'aria-label': `Quitar servicio ${idx + 1}`,
            onclick: () => { if (q.items.length > 1) q.items.splice(idx, 1); else q.items[0] = { desc: '', qty: '1', price: '' }; renderItems(); recalc(); },
          }, icon('x'))));
        requestAnimationFrame(() => autosize(desc));
      });
      recalc();
    }
    function addItem(desc) {
      const last = q.items[q.items.length - 1];
      if (last && !last.desc.trim() && !num(last.price)) { last.desc = desc; } else { q.items.push({ desc, qty: '1', price: '' }); }
      renderItems();
      const rows = $$('.item', itemsBox);
      const target = rows[rows.length - 1];
      (desc ? $$('input', target)[1] : $('textarea', target)).focus();
    }
    const chips = h('div', { class: 'chips', role: 'group', 'aria-label': 'Agregar servicio' },
      SERVICES.map(([label, desc]) => h('button', { class: 'chip', type: 'button', onclick: () => addItem(desc) }, label)));

    /* Descuento e IGV */
    const discType = h('select', { 'aria-label': 'Tipo de descuento' },
      h('option', { value: 'none' }, 'Sin descuento'), h('option', { value: 'percent' }, 'Porcentaje (%)'), h('option', { value: 'amount' }, 'Monto fijo (S/)'));
    discType.value = q.discount_type;
    const discVal = h('input', { type: 'text', inputmode: 'decimal', value: q.discount_value, placeholder: '0', 'aria-label': 'Valor del descuento' });
    const syncDisc = () => { discVal.disabled = q.discount_type === 'none'; };
    discType.addEventListener('change', () => { q.discount_type = discType.value; syncDisc(); recalc(); });
    bind(discVal, 'discount_value');
    syncDisc();

    const igvOptions = [['none', 'Sin IGV'], ['add', 'Más IGV (18%)'], ['included', 'IGV incluido']];
    const igvSeg = h('div', { class: 'seg', role: 'radiogroup', 'aria-label': 'IGV' },
      igvOptions.map(([v, t]) => {
        const r = h('input', { type: 'radio', name: 'igv', value: v });
        r.checked = q.igv_mode === v;
        r.addEventListener('change', () => { q.igv_mode = v; recalc(); });
        return h('label', {}, r, h('span', {}, t));
      }));

    const validDays = bind(h('input', { type: 'number', min: 1, max: 365, value: q.valid_days }), 'valid_days');
    const issue = bind(h('input', { type: 'date', value: q.issue_date }), 'issue_date');
    const status = h('select', {}, h('option', { value: 'enviada' }, 'Enviada'), h('option', { value: 'aceptada' }, 'Aceptada'), h('option', { value: 'rechazada' }, 'Rechazada'));
    status.value = q.status;
    status.addEventListener('change', () => { q.status = status.value; });
    const conditions = h('textarea', { rows: 5, maxlength: 3000 });
    conditions.value = q.conditions;
    conditions.addEventListener('input', () => { q.conditions = conditions.value; autosize(conditions); });

    /* Panel de total */
    const sumTotal = h('div', { class: 'big' }, 'S/ 0.00');
    const sumList = h('dl');
    const sumUntil = h('div', { class: 'until' });
    const rise = (() => {
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('viewBox', '0 0 150 150'); svg.setAttribute('class', 'rise'); svg.setAttribute('aria-hidden', 'true');
      svg.innerHTML = '<path d="M40 130 L72 102 L88 114 L124 60"/><polygon points="136,34 142,78 106,56"/>';
      return svg;
    })();

    function recalc() {
      const c = calc(q);
      amountEls.forEach((el, i) => { el.textContent = fmtMoney(c.items[i] || 0); });
      sumTotal.textContent = fmtMoney(c.total);
      const rows = [['Subtotal', fmtMoney(c.subtotal)]];
      if (c.disc > 0) rows.push(['Descuento', '- ' + fmtMoney(c.disc)]);
      if (q.igv_mode !== 'none') {
        if (c.base !== c.subtotal) rows.push(['Base imponible', fmtMoney(c.base)]);
        rows.push(['IGV (18%)', fmtMoney(c.igv)]);
      }
      sumList.replaceChildren(...rows.map(([k, v]) => h('div', {}, h('dt', {}, k), h('dd', {}, v))));
      const days = parseInt(q.valid_days, 10);
      sumUntil.textContent = q.issue_date && days > 0 ? `Válida hasta el ${addDays(q.issue_date, days)}` : '';
    }

    /* Guardado */
    const saveBtn = h('button', { class: 'btn outline on-dark-outline', type: 'button' }, 'Guardar');
    const pdfBtn = h('button', { class: 'btn on-dark', type: 'button' }, 'Guardar y abrir PDF');

    async function save(openPdf) {
      const popup = openPdf ? window.open('about:blank', '_blank') : null;
      saveBtn.disabled = pdfBtn.disabled = true;
      try {
        const payload = {
          ...q,
          client_doc: q.client_doc.trim(),
          items: q.items.filter((i) => i.desc.trim() || num(i.price)),
        };
        const saved = q.id
          ? await api('/quotes/' + q.id, { method: 'PUT', body: payload })
          : await api('/quotes', { method: 'POST', body: payload });
        const isNew = !q.id;
        q.id = saved.id; q.number = saved.number;
        title.textContent = saved.number;
        if (isNew) history.replaceState(null, '', '#/editar/' + saved.id);
        toast(`${saved.number} guardada.`);
        if (openPdf) {
          const url = `/api/quotes/${saved.id}/pdf`;
          if (popup) popup.location.href = url; else window.location.assign(url);
        }
      } catch (e) {
        if (popup) popup.close();
        toast(e.message, 'err');
      } finally { saveBtn.disabled = pdfBtn.disabled = false; }
    }
    saveBtn.addEventListener('click', () => save(false));
    pdfBtn.addEventListener('click', () => save(true));

    view.replaceChildren(
      h('div', { class: 'view-head' }, title, h('a', { class: 'btn ghost', href: '#/cotizaciones' }, 'Volver al historial')),
      h('div', { class: 'editor' },
        h('div', { class: 'sections' },
          h('section', { class: 'section' }, h('h2', {}, 'Cliente'),
            h('div', { class: 'grid-3' },
              h('label', { class: 'field' }, h('span', {}, 'Nombre o razón social'), name),
              h('label', { class: 'field' }, h('span', {}, 'DNI o RUC'), doc),
              h('label', { class: 'field' }, h('span', {}, 'Teléfono'), phone))),
          h('section', { class: 'section' }, h('h2', {}, 'Servicios'),
            h('div', { class: 'field' }, h('span', { class: 'legend' }, 'Agrega un servicio de tu catálogo'), chips),
            itemsBox,
            h('button', { class: 'btn outline add-row', type: 'button', onclick: () => addItem('') }, icon('plus'), 'Línea en blanco')),
          h('section', { class: 'section' }, h('h2', {}, 'Precio'),
            h('div', { class: 'field' }, h('span', { class: 'legend' }, 'IGV'), igvSeg),
            h('div', { class: 'field' }, h('span', { class: 'legend' }, 'Descuento'), h('div', { class: 'discount' }, discType, discVal))),
          h('section', { class: 'section' }, h('h2', {}, 'Condiciones'),
            h('div', { class: 'grid-3' },
              h('label', { class: 'field' }, h('span', {}, 'Fecha'), issue),
              h('label', { class: 'field' }, h('span', {}, 'Validez (días)'), validDays),
              h('label', { class: 'field' }, h('span', {}, 'Estado'), status)),
            h('label', { class: 'field' }, h('span', {}, 'Condiciones de pago y entrega'), conditions))),
        h('aside', { class: 'summary', 'aria-label': 'Resumen de la cotización' },
          rise,
          h('div', {}, h('div', { class: 'lbl' }, 'Total a cotizar'), sumTotal),
          sumList, sumUntil,
          h('div', { class: 'actions' }, pdfBtn, saveBtn))));

    renderItems();
    autosize(conditions);
    if (!id) name.focus();
  }

  /* ------------------------------------------------------------ comprobantes */
  const DOC_LABELS = { boleta: 'Boleta', factura: 'Factura', recibo: 'Recibo por honorarios' };
  const IGV_TEXT = { none: 'Sin IGV', add: 'Precios sin IGV, más IGV (18%)', included: 'Precios con IGV incluido' };

  function openEmitDialog(q) {
    let type = (q.client_doc || '').length === 11 ? 'factura' : 'boleta';
    const series = h('input', { type: 'text', maxlength: 4, autocomplete: 'off', autocapitalize: 'characters', spellcheck: 'false', 'aria-label': 'Serie' });
    const number = h('input', { type: 'text', inputmode: 'numeric', maxlength: 8, autocomplete: 'off', 'aria-label': 'Número' });
    const issue = h('input', { type: 'date', value: todayISO() });
    const warn = h('p', { class: 'form-error' });
    const err = h('p', { class: 'form-error', role: 'alert' });
    const submit = h('button', { class: 'btn primary', type: 'submit' }, 'Registrar comprobante');

    function checkWarn() {
      const doc = q.client_doc || '';
      if (type === 'factura' && doc.length !== 11) warn.textContent = 'La factura requiere el RUC (11 dígitos) del cliente. Edita la cotización y agrégalo.';
      else if (type === 'boleta' && Number(q.total) >= 700 && !doc) warn.textContent = 'Las boletas desde S/ 700 requieren DNI o RUC del cliente. Edita la cotización y agrégalo.';
      else warn.textContent = '';
    }
    async function suggest() {
      try { const sg = await api('/documents/suggest?doc_type=' + type); series.value = sg.series; number.value = sg.number; } catch { /* se escribe a mano */ }
    }
    const seg = h('div', { class: 'seg full', role: 'radiogroup', 'aria-label': 'Tipo de comprobante' },
      Object.entries({ boleta: 'Boleta', factura: 'Factura', recibo: 'Rec. honorarios' }).map(([v, t]) => {
        const r = h('input', { type: 'radio', name: 'doctype', value: v });
        r.checked = v === type;
        r.addEventListener('change', () => { type = v; checkWarn(); suggest(); });
        return h('label', {}, r, h('span', {}, t));
      }));

    const form = h('form', { novalidate: true, class: 'dlg-form' },
      h('h2', {}, 'Registrar comprobante'),
      h('p', { class: 'hint' }, `${q.number} · ${q.client_name} · ${fmtMoney(q.total)}. Emítelo en SUNAT y escribe aquí la serie y el número que te asignó. Deben coincidir con SUNAT.`),
      h('div', { class: 'field' }, h('span', { class: 'legend' }, 'Tipo'), seg),
      h('div', { class: 'grid-2' },
        h('label', { class: 'field' }, h('span', {}, 'Serie'), series),
        h('label', { class: 'field' }, h('span', {}, 'Número'), number)),
      h('label', { class: 'field' }, h('span', {}, 'Fecha de emisión'), issue),
      warn, err,
      h('div', { class: 'dlg-actions' },
        h('button', { class: 'btn ghost', type: 'button', onclick: () => dlg.close('no') }, 'Cancelar'), submit));
    const dlg = h('dialog', { class: 'dlg wide' }, form);
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      err.textContent = '';
      submit.disabled = true;
      try {
        const d = await api('/documents', { method: 'POST', body: { quote_id: q.id, doc_type: type, series: series.value, number: number.value, issue_date: issue.value } });
        dlg.close('ok');
        toast(`${d.label} registrado.`);
        location.hash = '#/comprobante/' + d.id;
      } catch (ex) { err.textContent = ex.message; } finally { submit.disabled = false; }
    });
    dlg.addEventListener('close', () => dlg.remove());
    document.body.append(dlg);
    dlg.showModal();
    checkWarn();
    suggest();
  }

  async function viewDocs() {
    const view = $('#view');
    const search = h('input', { type: 'search', placeholder: 'Buscar por número, cliente o DNI/RUC', 'aria-label': 'Buscar comprobantes' });
    const typeSel = h('select', { 'aria-label': 'Filtrar por tipo' },
      h('option', { value: '' }, 'Todos los tipos'),
      Object.entries(DOC_LABELS).map(([v, t]) => h('option', { value: v }, t)));
    const statusSel = h('select', { 'aria-label': 'Filtrar por estado' },
      h('option', { value: '' }, 'Todos los estados'), h('option', { value: 'emitido' }, 'Emitidos'), h('option', { value: 'anulado' }, 'Anulados'));
    const figures = h('div', { class: 'figures' });
    const listBox = h('div');
    view.replaceChildren(
      h('div', { class: 'view-head' },
        h('div', {}, h('h1', {}, 'Comprobantes'), h('p', {}, 'Registro de lo que emites en SUNAT.')),
        h('a', { class: 'btn outline', href: '/api/documents/export.csv' }, 'Exportar CSV')),
      figures,
      h('div', { class: 'filters three' }, search, typeSel, statusSel),
      listBox);

    async function load() {
      const data = await api('/documents?' + new URLSearchParams({ q: search.value, type: typeSel.value, status: statusSel.value }));
      figures.replaceChildren(
        h('div', { class: 'figure' }, h('b', {}, fmtMoney(data.stats.month_total)), h('span', {}, 'Emitido este mes')),
        h('div', { class: 'figure' }, h('b', {}, String(data.stats.month_count)), h('span', {}, 'Comprobantes del mes')));
      if (!data.documents.length) {
        const filtering = search.value || typeSel.value || statusSel.value;
        listBox.replaceChildren(h('div', { class: 'qlist empty' },
          h('h2', {}, filtering ? 'Sin resultados' : 'Aún no registras comprobantes'),
          h('p', {}, filtering ? 'Prueba con otros filtros.' : 'Desde Cotizaciones, usa el ícono de comprobante en la fila de una cotización.'),
          filtering ? null : h('a', { class: 'btn primary', href: '#/cotizaciones' }, 'Ir a cotizaciones')));
        return;
      }
      listBox.replaceChildren(h('div', { class: 'qlist' },
        h('div', { class: 'qhead doc' }, h('span', {}, 'Comprobante'), h('span', {}, 'Cliente'), h('span', {}, 'Total'), h('span', {}, 'Estado'), h('span', {}, '')),
        data.documents.map((d) => h('div', { class: 'qrow doc' },
          h('a', { class: 'num doc-link', href: '#/comprobante/' + d.id }, d.label),
          h('div', { class: 'who' }, h('b', {}, d.client_name), h('small', {}, `${d.type_label} · ${fmtDate(d.issue_date)}` + (d.client_doc ? ' · ' + d.client_doc : ''))),
          h('span', { class: 'total' }, fmtMoney(d.total)),
          h('span', { class: 'st' }, h('span', { class: 'badge b-' + d.status }, d.status === 'emitido' ? 'Emitido' : 'Anulado')),
          h('div', { class: 'acts' }, h('a', { class: 'icon-btn', href: '#/comprobante/' + d.id, title: 'Ver detalle', 'aria-label': 'Ver ' + d.label }, icon('eye')))))));
    }
    const reload = () => load().catch((e) => toast(e.message, 'err'));
    search.addEventListener('input', debounce(reload, 250));
    typeSel.addEventListener('change', reload);
    statusSel.addEventListener('change', reload);
    await load();
  }

  async function copyText(text) {
    try { await navigator.clipboard.writeText(text); toast('Copiado.'); }
    catch { toast('No se pudo copiar. Selecciona el texto manualmente.', 'err'); }
  }

  async function viewDoc(id) {
    const d = await api('/documents/' + id);
    const view = $('#view');
    const kv = (label, value, copy = true) => h('div', { class: 'kv' },
      h('dt', {}, label),
      h('dd', {}, value || '—', copy && value ? h('button', { class: 'copy', type: 'button', 'aria-label': 'Copiar ' + label, onclick: () => copyText(String(value)) }, 'Copiar') : null));
    const docKind = d.client_doc ? (d.client_doc.length === 11 ? 'RUC' : 'DNI') : 'Documento';
    const voided = d.status === 'anulado';

    const actions = h('div', { class: 'head-actions' },
      h('a', { class: 'btn ghost', href: '#/comprobantes' }, 'Volver'),
      d.quote_id ? h('a', { class: 'btn outline', href: '#/editar/' + d.quote_id }, 'Ver cotización') : null,
      voided ? null : h('button', {
        class: 'btn outline danger-text', type: 'button',
        onclick: async () => {
          if (!(await confirmDialog(`¿Anular ${d.label}? Esto solo marca el registro; recuerda anularlo también en SUNAT.`, 'Anular'))) return;
          try { await api(`/documents/${d.id}/void`, { method: 'PATCH' }); toast(d.label + ' anulado.'); viewDoc(id).catch((e) => toast(e.message, 'err')); }
          catch (e) { toast(e.message, 'err'); }
        },
      }, 'Anular'));

    const itemsTable = h('div', { class: 'table-wrap' },
      h('table', { class: 'dtable' },
        h('thead', {}, h('tr', {}, h('th', {}, 'Descripción'), h('th', { class: 'r' }, 'Cant.'), h('th', { class: 'r' }, 'P. unit.'), h('th', { class: 'r' }, 'Importe'))),
        h('tbody', {}, d.items.map((it) => h('tr', {},
          h('td', { class: 'desc' }, it.desc),
          h('td', { class: 'r' }, String(parseFloat(it.qty))),
          h('td', { class: 'r' }, fmtMoney(it.price)),
          h('td', { class: 'r' }, fmtMoney(it.amount)))))));

    const totals = [['Subtotal', fmtMoney(d.subtotal)]];
    if (Number(d.discount_amount) > 0) totals.push(['Descuento', '- ' + fmtMoney(d.discount_amount)]);
    if (d.igv_mode !== 'none') { totals.push(['Base imponible', fmtMoney(d.base)]); totals.push(['IGV (18%)', fmtMoney(d.igv)]); }

    view.replaceChildren(
      h('div', { class: 'view-head' },
        h('div', {}, h('h1', {}, d.label), h('p', {}, d.type_label + ' ', h('span', { class: 'badge b-' + d.status }, voided ? 'Anulado' : 'Emitido'))),
        actions),
      h('div', { class: 'notice' }, 'Este es un registro interno, no un comprobante válido. El documento oficial es el que emites en SUNAT con esta misma serie y número.'),
      h('div', { class: 'settings' },
        h('section', { class: 'section' }, h('h2', {}, 'Comprobante'),
          h('dl', { class: 'kvs' }, kv('Tipo', d.type_label, false), kv('Serie', d.series), kv('Número', d.number), kv('Fecha de emisión', fmtDate(d.issue_date)), kv('Moneda', 'Soles (PEN)', false))),
        h('section', { class: 'section' }, h('h2', {}, 'Cliente'),
          h('dl', { class: 'kvs' }, kv('Nombre o razón social', d.client_name), kv(docKind, d.client_doc), kv('Teléfono', d.client_phone))),
        h('section', { class: 'section' }, h('h2', {}, 'Detalle'), itemsTable),
        h('section', { class: 'section' }, h('h2', {}, 'Totales'),
          h('dl', { class: 'kvs' },
            kv('Tratamiento de IGV', IGV_TEXT[d.igv_mode], false),
            totals.map(([k, v]) => kv(k, v, false)),
            h('div', { class: 'kv total-line' }, h('dt', {}, 'Total'), h('dd', {}, fmtMoney(d.total), h('button', { class: 'copy', type: 'button', onclick: () => copyText(Number(d.total).toFixed(2)) }, 'Copiar')))))));
  }

  /* ------------------------------------------------------------ ajustes */
  async function viewSettings() {
    const view = $('#view');
    const s = state.settings = await api('/settings');
    const inputs = {};
    const field = (key, label, opts = {}) => {
      const el = opts.area
        ? h('textarea', { rows: opts.rows || 3, maxlength: opts.max || 600 })
        : h('input', { type: opts.type || 'text', maxlength: opts.max || 120, autocomplete: 'off', min: opts.min });
      el.value = s[key] || '';
      inputs[key] = el;
      return h('label', { class: 'field' }, h('span', {}, label), el, opts.hint ? h('small', {}, opts.hint) : null);
    };

    const businessForm = h('form', { novalidate: true },
      h('h2', {}, 'Datos del negocio'),
      h('p', { class: 'hint' }, 'Aparecen en el encabezado y el pie de cada PDF. Deja en blanco lo que no quieras mostrar.'),
      h('div', { class: 'grid-2' }, field('business_name', 'Nombre comercial', { max: 80 }), field('tagline', 'Lema', { max: 120 })),
      h('div', { class: 'grid-2' }, field('ruc', 'RUC', { max: 20 }), field('phone', 'Teléfono / WhatsApp', { max: 40 })),
      h('div', { class: 'grid-2' }, field('email', 'Correo', { max: 120 }), field('web', 'Web o redes', { max: 120 })),
      field('address', 'Dirección', { max: 200 }),
      field('payment_info', 'Datos de pago', { area: true, rows: 3, max: 600, hint: 'Ej.: Yape 999 999 999 · BCP cuenta 000-0000000-0-00 · CCI 000…' }),
      h('h2', {}, 'Valores por defecto'),
      field('default_conditions', 'Condiciones de las cotizaciones nuevas', { area: true, rows: 4, max: 3000 }),
      h('div', { class: 'grid-2' },
        field('default_valid_days', 'Validez (días)', { type: 'number', min: 1 }),
        field('next_number', 'Próximo número de cotización', { type: 'number', min: 1, hint: 'Se usa en la siguiente cotización que crees (COT-0001, COT-0002…).' })),
      h('div', { class: 'save-row' }, h('button', { class: 'btn primary', type: 'submit' }, 'Guardar ajustes')));
    businessForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      try {
        const body = Object.fromEntries(Object.entries(inputs).map(([k, el]) => [k, el.value]));
        state.settings = await api('/settings', { method: 'PUT', body });
        toast('Ajustes guardados.');
      } catch (ex) { toast(ex.message, 'err'); }
    });

    const cur = h('input', { type: 'password', autocomplete: 'current-password' });
    const nw = h('input', { type: 'password', autocomplete: 'new-password', minlength: 10 });
    const rep = h('input', { type: 'password', autocomplete: 'new-password' });
    const passForm = h('form', { novalidate: true },
      h('h2', {}, 'Contraseña'),
      h('p', { class: 'hint' }, 'Mínimo 10 caracteres. Una frase larga es más segura que una palabra con símbolos.'),
      h('label', { class: 'field' }, h('span', {}, 'Contraseña actual'), cur),
      h('div', { class: 'grid-2' },
        h('label', { class: 'field' }, h('span', {}, 'Contraseña nueva'), nw),
        h('label', { class: 'field' }, h('span', {}, 'Repite la nueva'), rep)),
      h('div', { class: 'save-row' }, h('button', { class: 'btn primary', type: 'submit' }, 'Cambiar contraseña')));
    passForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (nw.value !== rep.value) { toast('Las contraseñas nuevas no coinciden.', 'err'); return; }
      try {
        await api('/password', { method: 'POST', body: { current: cur.value, new: nw.value } });
        cur.value = nw.value = rep.value = '';
        toast('Contraseña actualizada.');
      } catch (ex) { toast(ex.message, 'err'); }
    });

    view.replaceChildren(
      h('div', { class: 'view-head' }, h('h1', {}, 'Ajustes')),
      h('div', { class: 'settings' },
        businessForm, passForm,
        h('section', { class: 'field' },
          h('h2', {}, 'Respaldo'),
          h('p', { class: 'hint' }, 'Descarga una copia de toda la base de datos (clientes y cotizaciones). Hazlo con regularidad y guárdala fuera del servidor.'),
          h('div', { class: 'save-row' }, h('a', { class: 'btn outline', href: '/api/backup' }, 'Descargar respaldo')))));
  }

  /* ------------------------------------------------------------ arranque */
  async function boot() {
    bindLogin();
    window.addEventListener('hashchange', route);
    try {
      const res = await fetch('/api/session', { credentials: 'same-origin' });
      const info = await res.json();
      state.csrf = info.csrf;
      if (info.authenticated) await showApp(); else showLogin();
    } catch {
      showLogin();
      $('#login-error').textContent = 'No se pudo conectar con el servidor.';
    }
  }
  boot();
})();
