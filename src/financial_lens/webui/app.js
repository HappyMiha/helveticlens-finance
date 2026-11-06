/* Financial Lens local web interface. Talks only to the service on this computer.
   All text from documents is untrusted: it is always inserted as text, never as HTML. */
(function () {
  'use strict';

  var CSRF = '';
  var state = { period: 'this_month', mode: 'expenses', group: 'category', path: [], selected: null, tree: null };

  // ------------------------------------------------------------ helpers
  function el(tag, attrs, children) {
    var e = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'class') e.className = attrs[k];
      else if (k === 'text') e.textContent = attrs[k];
      else if (k === 'style') e.style.cssText = attrs[k]; // CSSOM: allowed by the strict CSP, unlike style=""
      else if (k.slice(0, 2) === 'on') e.addEventListener(k.slice(2), attrs[k]);
      else e.setAttribute(k, attrs[k]);
    });
    (children || []).forEach(function (c) { if (c != null) e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return e;
  }
  function chf(v) {
    var n = Number(v || 0), neg = n < 0;
    var p = Math.abs(n).toFixed(2).split('.');
    return (neg ? '-' : '') + 'CHF ' + p[0].replace(/\B(?=(\d{3})+(?!\d))/g, '’') + '.' + p[1];
  }
  var LABEL = { confirmed: 'Confirmed', needs_review: 'Needs review', unconfirmed: 'Unconfirmed' };
  function status(s) { return el('span', { class: 'st ' + s, text: '● ' + (LABEL[s] || s) }); }
  function toast(msg, ms) {
    var t = document.getElementById('toast'); t.textContent = msg; t.hidden = false;
    clearTimeout(toast.t); toast.t = setTimeout(function () { t.hidden = true; }, ms || 6000);
  }
  function api(method, path, body, raw) {
    var opts = { method: method, credentials: 'same-origin', headers: {} };
    if (method !== 'GET') opts.headers['X-FL-CSRF'] = CSRF;
    if (body instanceof FormData) opts.body = body;
    else if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
    return fetch(path, opts).then(function (r) {
      if (!r.ok) return r.json().catch(function () { return {}; }).then(function (j) { throw new Error(j.detail || ('Error ' + r.status)); });
      return raw ? r : r.json();
    });
  }
  function range() {
    var d = new Date(), y = d.getFullYear(), m = d.getMonth(), f = function (x) { return x.toISOString().slice(0, 10); };
    var iso = function (yy, mm, dd) { return f(new Date(Date.UTC(yy, mm, dd))); };
    switch (state.period) {
      case 'last_month': return [iso(y, m - 1, 1), iso(y, m, 0)];
      case 'this_quarter': return [iso(y, Math.floor(m / 3) * 3, 1), iso(y, m, d.getDate())];
      case 'this_year': return [iso(y, 0, 1), iso(y, m, d.getDate())];
      case 'last_year': return [iso(y - 1, 0, 1), iso(y - 1, 11, 31)];
      case 'all': return ['1970-01-01', '2999-12-31'];
      default: return [iso(y, m, 1), iso(y, m, d.getDate())];
    }
  }
  function q() { var r = range(); return 'start=' + r[0] + '&end=' + r[1]; }
  function view() { return document.getElementById('view'); }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; }
  function card(title, children) { return el('section', { class: 'card' }, [title ? el('h3', { text: title }) : null].concat(children)); }

  // ------------------------------------------------------------ treemap
  function squarify(vals, x, y, w, h) {
    var total = vals.reduce(function (a, b) { return a + b; }, 0), out = [];
    if (!total) return vals.map(function () { return [x, y, 0, 0]; });
    var areas = vals.map(function (v) { return v / total * w * h; }), i = 0;
    while (i < areas.length) {
      var side = Math.min(w, h), row = [areas[i]], j = i + 1;
      var worst = function (r) {
        var s = r.reduce(function (a, b) { return a + b; }, 0), mx = Math.max.apply(null, r), mn = Math.min.apply(null, r);
        return Math.max(side * side * mx / (s * s), (s * s) / (side * side * mn));
      };
      while (j < areas.length && worst(row.concat(areas[j])) <= worst(row)) { row.push(areas[j]); j++; }
      var s = row.reduce(function (a, b) { return a + b; }, 0), off;
      if (w >= h) { var cw = s / h; off = y; row.forEach(function (a) { out.push([x, off, cw, a / cw]); off += a / cw; }); x += cw; w -= cw; }
      else { var rh = s / w; off = x; row.forEach(function (a) { out.push([off, y, a / rh, rh]); off += a / rh; }); y += rh; h -= rh; }
      i = j;
    }
    return out;
  }
  function nodeAt(tree, path) {
    var n = tree;
    for (var i = 0; i < path.length; i++) { n = (n.children || []).find(function (c) { return c.name === path[i]; }); if (!n) return null; }
    return n;
  }
  function entries(node) {
    var out = (node.children || []).map(function (c) { return { kind: 'cat', name: c.name, value: Number(c.total), count: c.count }; });
    (node.operations || []).forEach(function (o) { out.push({ kind: 'op', name: o.counterparty || o.kind, value: Number(o.amount), op: o }); });
    return out.filter(function (e) { return e.value > 0; }).sort(function (a, b) { return b.value - a.value; });
  }
  function tone(k) {
    var hues = state.mode === 'income' ? ['--tm-in-1', '--tm-in-2'] : ['--tm-1', '--tm-2', '--tm-3', '--tm-4', '--tm-5'];
    return 'var(' + hues[k % hues.length] + ')';
  }
  function drawTreemap(box, list, crumbs, totalEl, evidence) {
    var node = nodeAt(state.tree, state.path) || state.tree;
    if (!nodeAt(state.tree, state.path)) state.path = [];
    var es = entries(node), wpx = box.clientWidth || 600;
    box.style.height = Math.max(240, Math.min(wpx * (wpx < 600 ? 1 : 0.58), window.innerHeight * 0.62)) + 'px';
    clear(box); clear(list); clear(crumbs);
    if (!es.length) { box.appendChild(el('div', { class: 'empty', text: 'Nothing in this period yet. Add receipts, invoices or bank statements.' })); }
    var rects = squarify(es.map(function (e) { return e.value; }), 0, 0, 100, 100), total = Number(node.total) || 1;
    es.forEach(function (e, k) {
      var r = rects[k], share = Math.round(e.value / total * 100);
      var open = function () {
        if (e.kind === 'cat') { state.path = state.path.concat([e.name]); state.selected = null; renderOverview(); }
        else { state.selected = e.op.id; showEvidence(evidence, e.op.id); drawTreemap(box, list, crumbs, totalEl, evidence); }
      };
      var b = el('button', { type: 'button', class: 'tile' + (e.kind === 'op' ? ' st-' + e.op.verification : '') + (e.op && e.op.id === state.selected ? ' sel' : ''),
        title: e.name + ' · ' + chf(e.value) + ' · ' + share + ' %', 'aria-label': e.name + ', ' + chf(e.value), onclick: open },
        [el('strong', { text: e.name }), el('span', { class: 'num', text: chf(e.value) + ' · ' + share + ' %' })]);
      b.style.left = r[0] + '%'; b.style.top = r[1] + '%'; b.style.width = r[2] + '%'; b.style.height = r[3] + '%';
      b.style.background = tone(k);
      var pw = wpx * r[2] / 100, ph = box.clientHeight * r[3] / 100;
      if (pw < 78 || ph < 44) b.classList.add('compact');
      box.appendChild(b);
      list.appendChild(el('li', {}, [el('button', { type: 'button', onclick: open }, [
        el('span', { class: 'sw', style: 'background:' + tone(k) }), el('span', { class: 'nm', text: e.name }),
        el('span', { class: 'am num', text: chf(e.value) + ' · ' + share + ' %' })])]));
    });
    ['All ' + state.mode].concat(state.path).forEach(function (name, i) {
      if (i) crumbs.appendChild(el('span', { class: 'muted', text: '/' }));
      var b = el('button', { type: 'button', text: name, onclick: function () { state.path = state.path.slice(0, i); state.selected = null; renderOverview(); } });
      if (i === state.path.length) b.setAttribute('aria-current', 'page');
      crumbs.appendChild(b);
    });
    totalEl.textContent = chf(node.total) + ' · ' + node.count + ' records';
  }

  function showEvidence(box, id) {
    clear(box).appendChild(el('p', { class: 'muted', text: 'Loading…' }));
    api('GET', '/operations/' + id).then(function (d) {
      clear(box);
      box.appendChild(el('h3', { text: 'Evidence' }));
      box.appendChild(el('div', { class: 'kpi', text: d.counterparty || d.kind }));
      box.appendChild(el('div', { class: 'num', text: chf(Math.abs(d.amount)) + ' · ' + d.op_date }));
      box.appendChild(el('p', {}, [status(d.verification), ' ', el('span', { class: 'muted', text: d.verification_reason || '' })]));
      var dl = el('dl');
      [['Category', (d.category_path || []).join(' / ')], ['Kind', d.kind], ['Due', d.due_date || '—'], ['Read by', d.method],
        ['Tags', (d.tags || []).join(', ') || '—']].forEach(function (p) { dl.appendChild(el('dt', { text: p[0] })); dl.appendChild(el('dd', { text: p[1] })); });
      box.appendChild(dl);
      var prov = d.provenance || {};
      var keys = Object.keys(prov).filter(function (k) { return prov[k] && typeof prov[k] === 'object' && prov[k].quote; });
      if (keys.length) {
        box.appendChild(el('h4', { text: 'Where each value came from' }));
        keys.forEach(function (k) {
          box.appendChild(el('div', {}, [el('span', { class: 'muted', text: k + (prov[k].location ? ' · ' + prov[k].location : '') }), el('code', { text: prov[k].quote })]));
        });
      }
      if ((d.documents || []).length) {
        box.appendChild(el('h4', { text: 'Documents' }));
        d.documents.forEach(function (doc) {
          box.appendChild(el('p', {}, [el('a', { href: '/documents/' + doc.id + '/original', target: '_blank', rel: 'noopener', text: doc.filename }),
            el('span', { class: 'muted', text: ' · ' + doc.role + ' · sha256 ' + String(doc.sha256).slice(0, 12) + '…' })]));
        });
      }
      if ((d.links || []).length) {
        box.appendChild(el('h4', { text: 'Linked' }));
        d.links.forEach(function (l) {
          box.appendChild(el('p', {}, [l.other_kind + ' ' + l.other_date + ' · ' + chf(Math.abs(l.other_amount)) + ' · ' + l.status,
            el('br'), el('span', { class: 'muted', text: (l.reasons || []).join('; ') })]));
        });
      }
      box.appendChild(el('h4', { text: 'History' }));
      (d.history || []).forEach(function (h) {
        box.appendChild(el('p', { class: 'muted', text: 'r' + h.revision + ' · ' + String(h.created_at).slice(0, 19) + ' · ' + h.agent + ' · ' + h.change_reason + ' → ' + (LABEL[h.verification] || h.verification) }));
      });
    }).catch(function (e) { clear(box).appendChild(el('p', { text: e.message })); });
  }

  // ------------------------------------------------------------ pages
  function renderOverview() {
    var v = clear(view());
    var kpis = el('div', { class: 'grid kpis' });
    var box = el('div', { class: 'treemap', role: 'group', 'aria-label': 'Treemap' });
    var list = el('ul', { class: 'list', 'aria-label': 'Areas' }), crumbs = el('nav', { class: 'crumbs', 'aria-label': 'Breadcrumb' });
    var total = el('p', { class: 'muted num' });
    var evidence = el('section', { class: 'card ev' }, [el('h3', { text: 'Evidence' }), el('p', { class: 'muted', text: 'Select a record to see where its numbers came from.' })]);
    var side = el('div', { class: 'grid' });
    v.appendChild(kpis);
    v.appendChild(el('div', { class: 'grid two' }, [card('', [crumbs, box, total, list]), el('div', { class: 'grid' }, [evidence, side])]));
    api('GET', '/dashboard?' + q()).then(function (d) {
      [['Balance (income − expenses)', chf(d.balance)], ['Income', chf(d.income)], ['Expenses', chf(d.expenses)],
        ['Unconfirmed / unpaid', d.unconfirmed.length + ' / ' + d.unpaid.length]].forEach(function (p) {
        kpis.appendChild(card(p[0], [el('div', { class: 'kpi num', text: p[1] })]));
      });
      var mk = function (title, rows, fn) {
        var t = el('table'), tb = el('tbody');
        rows.slice(0, 8).forEach(function (r) { tb.appendChild(fn(r)); });
        t.appendChild(tb);
        side.appendChild(card(title, [rows.length ? t : el('p', { class: 'muted', text: 'None.' })]));
      };
      mk('Unconfirmed operations', d.unconfirmed, function (r) {
        return el('tr', { onclick: function () { showEvidence(evidence, r.operation_id); }, style: 'cursor:pointer' },
          [el('td', { text: r.op_date }), el('td', { text: r.counterparty }), el('td', { class: 'r num', text: chf(Math.abs(r.amount)) })]);
      });
      mk('Unpaid invoices', d.unpaid, function (r) {
        return el('tr', { onclick: function () { showEvidence(evidence, r.operation_id); }, style: 'cursor:pointer' },
          [el('td', { text: r.due_date || r.op_date }), el('td', { text: r.counterparty }), el('td', { class: 'r num', text: chf(r.amount) })]);
      });
    }).catch(function (e) { toast(e.message); });
    api('GET', '/treemap?' + q() + '&mode=' + state.mode + '&group=' + state.group).then(function (t) {
      state.tree = t; drawTreemap(box, list, crumbs, total, evidence);
      if (state.selected) showEvidence(evidence, state.selected);
    }).catch(function (e) { toast(e.message); });
  }

  function table(headers, rows) {
    var t = el('table', {}, [el('thead', {}, [el('tr', {}, headers.map(function (h) { return el('th', { class: h[1] || '', text: h[0] }); }))])]);
    var tb = el('tbody'); rows.forEach(function (r) { tb.appendChild(r); }); t.appendChild(tb); return t;
  }

  function renderTransactions() {
    var v = clear(view());
    api('GET', '/ui/transactions?' + q()).then(function (rows) {
      v.appendChild(card('Transactions · ' + rows.length, [rows.length ? table([['Date'], ['Kind'], ['Counterparty'], ['Category'], ['Amount', 'r'], ['Status']],
        rows.map(function (r) {
          return el('tr', {}, [el('td', { text: r.op_date }), el('td', { text: r.kind }),
            el('td', {}, [r.source_document_id ? el('a', { href: '#/upload/' + r.source_document_id, title: 'Open its upload', text: r.counterparty || '—' }) : (r.counterparty || '—')]),
            el('td', { text: r.category }),
            el('td', { class: 'r num', text: chf(r.amount) }), el('td', {}, [status(r.verification)])]);
        })) : el('p', { class: 'empty', text: 'No records in this period.' })]));
    }).catch(function (e) { toast(e.message); });
  }

  var TYPE = { receipt: 'Receipt', invoice: 'Invoice', bank_statement: 'Bank statement', payslip: 'Payslip', unknown: 'Not recognised' };
  function renderDocuments() {
    var v = clear(view());
    api('GET', '/documents').then(function (docs) {
      v.appendChild(card('Uploads · ' + docs.length, [docs.length ? table([['Received'], ['File'], ['Type'], ['Status'], ['Records', 'r'], ['', 'r']],
        docs.map(function (d) {
          var open = function () { location.hash = '#/upload/' + d.id; };
          return el('tr', { class: 'click', onclick: open }, [el('td', { text: String(d.received_at).slice(0, 16).replace('T', ' ') }),
            el('td', {}, [el('a', { href: '#/upload/' + d.id, text: d.filename })]),
            el('td', { text: TYPE[d.doc_type] || d.doc_type }), el('td', { text: d.processing_status.replace('_', ' ') }),
            el('td', { class: 'r', text: String(d.operations) }),
            el('td', { class: 'r' }, [el('a', { class: 'btn small', href: '#/upload/' + d.id, text: 'Open' })])]);
        })) : el('p', { class: 'empty', text: 'No uploads yet. Drop files anywhere on this page.' })]));
    }).catch(function (e) { toast(e.message); });
  }

  var CATS = null;
  function categoryPaths() {
    if (CATS) return Promise.resolve(CATS);
    return api('GET', '/categories').then(function (cs) {
      CATS = cs.filter(function (c) { return !c.archived; }).map(function (c) { return c.path.join(' / '); }); return CATS;
    });
  }
  function catSelect(current) {
    var s = el('select', { 'aria-label': 'Category' });
    (CATS || []).forEach(function (p) { var o = el('option', { value: p, text: p }); if (p === current) o.selected = true; s.appendChild(o); });
    if (current && (CATS || []).indexOf(current) < 0) s.insertBefore(el('option', { value: current, text: current, selected: 'selected' }), s.firstChild);
    return s;
  }

  function renderUpload() {
    var id = location.hash.split('/')[2], v = clear(view());
    v.appendChild(el('p', { class: 'muted', text: 'Loading…' }));
    Promise.all([api('GET', '/ui/uploads/' + id), categoryPaths()]).then(function (res) {
      var d = res[0]; clear(v);
      var src = '/documents/' + d.id + '/original';
      var media = String(d.media_type || '');
      var preview = media.indexOf('image/') === 0 ? el('img', { src: src, alt: d.filename, class: 'preview' })
        : media === 'application/pdf' ? el('iframe', { src: src, title: d.filename, class: 'preview' })
        : el('pre', { class: 'preview text', text: d.text || '(no preview for this file type)' });
      var head = el('div', { class: 'up-head' }, [
        el('a', { href: '#/documents', class: 'muted', text: '← Uploads' }),
        el('h2', { text: d.filename }),
        el('p', { class: 'muted', text: (TYPE[d.doc_type] || d.doc_type) + ' · added ' + String(d.received_at).slice(0, 16).replace('T', ' ') +
          ' · ' + d.records.length + ' record(s) · ' + chf(Math.abs(d.total)) + ' · read by ' + (d.engines || []).join(', ') }),
        el('div', { class: 'nag-actions' }, [
          el('a', { class: 'btn small', href: src, target: '_blank', rel: 'noopener', text: 'Open file' }),
          d.doc_type === 'bank_statement' ? null : rereadButton(d.id, renderUpload),
          el('button', { class: 'btn small danger', text: 'Delete upload', onclick: function () {
            if (!confirm('Delete “' + d.filename + '” and the ' + d.records.length + ' record(s) read from it? Records it was only attached to stay.')) return;
            api('DELETE', '/ui/uploads/' + d.id).then(function (r) {
              toast('Deleted. ' + r.deleted_records + ' record(s) removed.'); location.hash = '#/documents'; refreshInboxCount();
            }).catch(function (e) { toast(e.message); });
          } })])]);
      var recBox = el('div', { class: 'recs' });
      var drawRecords = function (records) {
        clear(recBox);
        if (!records.length) recBox.appendChild(el('p', { class: 'muted', text: 'Nothing was recorded from this file. Add a record below if something is missing.' }));
        else records.forEach(function (r) { recBox.appendChild(recordRow(r, d)); });
      };
      drawRecords(d.records);
      var reading = el('details', {}, [el('summary', { text: 'Everything read from the file' })]);
      if (d.reading) reading.appendChild(readingView(d.reading));
      if (d.analysis) reading.appendChild(analysisView(d.analysis));
      reading.appendChild(el('h4', { text: 'Text' }));
      reading.appendChild(el('pre', { class: 'mono pre', text: d.text || '—' }));
      v.appendChild(el('div', { class: 'grid up' }, [
        card('', [preview]),
        el('div', { class: 'grid' }, [card('', [head]), card('Records from this file', [recBox, addRecordForm(d)]), card('', [reading])])]));
    }).catch(function (e) { clear(v).appendChild(el('p', { class: 'empty', text: e.message })); });
  }

  function recordRow(r, d) {
    var path = (r.category_path || []).join(' / ');
    var attached = r.source_document_id !== d.id;
    var body = el('div', { class: 'rec-edit', hidden: 'hidden' });
    var view = el('div', { class: 'rec-view' }, [
      el('div', { class: 'rec-main' }, [
        el('span', { class: 'muted num', text: r.op_date }),
        el('strong', { text: r.counterparty || r.kind }),
        el('span', { class: 'chip', text: path }),
        (r.tags || []).length ? el('span', { class: 'muted small', text: '# ' + r.tags.join(', ') }) : null,
        el('span', { class: 'grow' }),
        el('span', { class: 'num rec-amt', text: chf(r.amount) })]),
      el('div', { class: 'rec-sub' }, [status(r.verification), ' ',
        el('span', { class: 'muted small', text: [r.kind, attached ? 'from an earlier upload; this file is attached to it' : '', r.description || ''].filter(Boolean).join(' · ') }),
        el('span', { class: 'grow' }),
        el('button', { class: 'btn small', text: 'Edit', onclick: function () { body.hidden = !body.hidden; } }), ' ',
        el('button', { class: 'btn small', text: 'Delete', 'aria-label': 'Delete this record', onclick: function () {
          if (!confirm('Delete this record (' + (r.counterparty || r.kind) + ', ' + chf(Math.abs(r.amount)) + ')?')) return;
          api('DELETE', '/ui/records/' + r.operation_id).then(function () { toast('Deleted.'); renderUpload(); refreshInboxCount(); })
            .catch(function (e) { toast(e.message); });
        } })])]);
    var date = el('input', { type: 'date', value: r.op_date });
    var who = el('input', { type: 'text', value: r.counterparty || '' });
    var desc = el('input', { type: 'text', value: r.description || '' });
    var cat = catSelect(path);
    var tags = el('input', { type: 'text', value: (r.tags || []).join(', '), placeholder: 'e.g. holiday, family' });
    var sign = Number(r.amount) < 0 ? -1 : 1;
    var amt = el('input', { type: 'text', value: Math.abs(Number(r.amount)).toFixed(2), inputmode: 'decimal' });
    body.appendChild(el('form', { class: 'form', onsubmit: function (e) {
      e.preventDefault();
      var changes = {}, a = Number(String(amt.value).replace(/[’' ]/g, '').replace(',', '.'));
      if (isNaN(a)) { toast('The amount is not a number.'); return; }
      if (date.value !== r.op_date) changes.op_date = date.value;
      if (who.value !== (r.counterparty || '')) changes.counterparty = who.value;
      if (desc.value !== (r.description || '')) changes.description = desc.value;
      if (cat.value !== path) changes.category = cat.value.split(' / ');
      if (Math.abs(a - Math.abs(Number(r.amount))) > 0.0001) changes.amount = (sign * a).toFixed(2);
      changes.confirm = true;
      var wantTags = tags.value.split(',').map(function (t) { return t.trim(); }).filter(Boolean);
      api('POST', '/operations/' + r.operation_id + '/corrections', { changes: changes, reason: 'edited on the upload page' })
        .then(function () { return api('PUT', '/ui/records/' + r.operation_id + '/tags', { tags: wantTags }); })
        .then(function () { toast('Saved and confirmed.'); renderUpload(); refreshInboxCount(); })
        .catch(function (x) { toast(x.message); });
    } }, [field('Date', date), field('Counterparty', who), field('Amount (' + r.currency + (sign < 0 ? ', paid out' : '') + ')', amt),
      field('Category', cat), field('Tags', tags), el('label', { class: 'wide' }, ['Description', desc]),
      el('button', { class: 'btn primary', type: 'submit', text: 'Save and confirm' })]));
    return el('div', { class: 'rec' }, [view, body]);
  }

  function addRecordForm(d) {
    var kind = el('select', { 'aria-label': 'Kind' }, [['receipt', 'Purchase (receipt)'], ['invoice', 'Bill (invoice)'], ['expense', 'Other expense'], ['income', 'Income']].map(function (k) { return el('option', { value: k[0], text: k[1] }); }));
    var date = el('input', { type: 'date', value: new Date().toISOString().slice(0, 10) }), who = el('input', { type: 'text', placeholder: 'e.g. Migros' });
    var amt = el('input', { type: 'text', placeholder: '0.00' }), desc = el('input', { type: 'text', placeholder: 'optional' });
    var cat = catSelect(''); cat.insertBefore(el('option', { value: '', text: 'Choose automatically', selected: 'selected' }), cat.firstChild);
    var form = el('form', { class: 'form', onsubmit: function (e) {
      e.preventDefault();
      var a = String(amt.value).replace(/[’' ]/g, '').replace(',', '.');
      if (!a || isNaN(Number(a))) { toast('Enter an amount.'); return; }
      api('POST', '/ui/uploads/' + d.id + '/records', { kind: kind.value, amount: Number(a).toFixed(2), op_date: date.value, counterparty: who.value,
        description: desc.value, category: cat.value ? cat.value.split(' / ') : null })
        .then(function () { toast('Added.'); renderUpload(); }).catch(function (x) { toast(x.message); });
    } }, [field('Kind', kind), field('Date', date), field('Counterparty', who), field('Amount (CHF)', amt), field('Description', desc), field('Category', cat),
      el('button', { class: 'btn primary', type: 'submit', text: 'Add record' })]);
    return el('details', { class: 'add' }, [el('summary', { text: '+ Add a record the reading missed' }), form]);
  }

  function readingView(rd) {
    var box = el('div', {}, [el('h4', { text: 'Apertus analysis' + (rd.model ? ' · ' + rd.model : '') })]);
    var dl = el('dl', { class: 'kv' });
    [['Merchant', rd.merchant], ['Summary', rd.summary], ['Date', rd.date], ['Total', rd.total], ['VAT', rd.vat], ['Payment', rd.payment],
      ['Category', rd.category], ['Checked', rd.check]].forEach(function (p) { if (p[1]) { dl.appendChild(el('dt', { text: p[0] })); dl.appendChild(el('dd', { text: String(p[1]) })); } });
    box.appendChild(dl);
    if ((rd.items || []).length) box.appendChild(table([['Item'], ['Qty', 'r'], ['Amount', 'r']], rd.items.map(function (i) {
      return el('tr', {}, [el('td', { text: i.name || '' }), el('td', { class: 'r', text: i.qty == null ? '' : String(i.qty) }), el('td', { class: 'r num', text: i.amount == null ? '' : String(i.amount) })]);
    })));
    return box;
  }
  function analysisView(an) {
    var box = el('div', {}, [el('h4', { text: 'Checks' })]);
    (an.checks || []).forEach(function (c) { box.appendChild(el('p', { class: 'muted', text: (c.ok ? '✓ ' : '✗ ') + c.name + (c.detail ? ' — ' + c.detail : '') })); });
    (an.problems || []).forEach(function (p) { box.appendChild(el('p', { class: 'muted', text: '⚠ ' + p })); });
    return box;
  }

  function renderInbox() {
    var v = clear(view());
    api('GET', '/ui/inbox').then(function (d) {
      var links = d.links.map(function (l) {
        var decide = function (accept) {
          api('POST', '/links/' + l.id + '/decision', { accept: accept }).then(function () { toast(accept ? 'Linked.' : 'Rejected.'); renderInbox(); refreshInboxCount(); })
            .catch(function (e) { toast(e.message); });
        };
        return el('tr', {}, [el('td', { text: l.op_date }), el('td', { text: l.counterparty + ' ↔ ' + (l.other || '') }),
          el('td', { class: 'r num', text: chf(l.amount) }), el('td', { class: 'muted', text: (l.reasons || []).join('; ') }),
          el('td', { class: 'r' }, [el('button', { class: 'btn small primary', text: 'Confirm', onclick: function () { decide(true); } }), ' ',
            el('button', { class: 'btn small', text: 'Reject', onclick: function () { decide(false); } })])]);
      });
      v.appendChild(card('Proposed links · ' + d.links.length, [links.length ? table([['Date'], ['Between'], ['Amount', 'r'], ['Why'], ['', 'r']], links)
        : el('p', { class: 'muted', text: 'Nothing to decide.' })]));
      v.appendChild(card('Needs review · ' + d.review.length, [d.review.length ? table([['Date'], ['Counterparty'], ['Amount', 'r'], ['Reason']],
        d.review.map(function (r) { return el('tr', {}, [el('td', { text: r.op_date }), el('td', { text: r.counterparty }), el('td', { class: 'r num', text: chf(Math.abs(r.amount)) }), el('td', { class: 'muted', text: r.verification_reason })]); }))
        : el('p', { class: 'muted', text: 'Everything reconciles.' })]));
      v.appendChild(card('Documents waiting · ' + d.documents.length, [d.documents.length ? table([['File'], ['Type'], ['Status']],
        d.documents.map(function (x) { return el('tr', {}, [el('td', {}, [el('a', { href: '/documents/' + x.id + '/original', target: '_blank', rel: 'noopener', text: x.filename })]), el('td', { text: x.doc_type }), el('td', { text: x.processing_status })]); }))
        : el('p', { class: 'muted', text: 'None.' })]));
    }).catch(function (e) { toast(e.message); });
  }

  function renderAnalytics() {
    var v = clear(view()), r = range();
    var slots = [el('div'), el('div'), el('div')]; slots.forEach(function (x) { v.appendChild(x); });
    v = { appendChild: function (c) { var title = c.querySelector('h3').textContent; slots[title.indexOf('Cash') === 0 ? 0 : title.indexOf('Spending') === 0 ? 1 : 2].appendChild(c); } };
    var start = r[0] < '1990' ? (new Date().getFullYear() - 4) + '-01-01' : r[0];
    api('GET', '/analytics/cash-flow?start=' + start + '&end=' + r[1]).then(function (rows) {
      v.appendChild(card('Cash flow and savings', [table([['Month'], ['Income', 'r'], ['Expenses', 'r'], ['Net', 'r'], ['Savings', 'r']],
        rows.map(function (x) { return el('tr', {}, [el('td', { text: x.month }), el('td', { class: 'r num', text: chf(x.income) }), el('td', { class: 'r num', text: chf(x.expenses) }), el('td', { class: 'r num', text: chf(x.net) }), el('td', { class: 'r num', text: chf(x.cumulative) })]); }))]));
    });
    api('GET', '/analytics/counterparties?' + q()).then(function (rows) {
      v.appendChild(card('Spending by counterparty', [table([['Counterparty'], ['Total', 'r'], ['Records', 'r']],
        rows.map(function (x) { return el('tr', {}, [el('td', { text: x.counterparty }), el('td', { class: 'r num', text: chf(x.total) }), el('td', { class: 'r', text: String(x.count) })]); }))]));
    });
    api('GET', '/recurring').then(function (rec) {
      v.appendChild(card('Recurring payments', [rec.detected.length ? table([['Counterparty'], ['Cadence'], ['Typical', 'r'], ['Next expected']],
        rec.detected.map(function (x) { return el('tr', {}, [el('td', { text: x.counterparty }), el('td', { text: x.cadence }), el('td', { class: 'r num', text: chf(x.amount) }), el('td', { text: x.next_expected })]); }))
        : el('p', { class: 'muted', text: 'No regular payments detected yet.' })]));
    });
  }

  function renderAsk() {
    var v = clear(view()), out = el('div');
    var input = el('input', { type: 'search', placeholder: 'e.g. How much did I spend on food this year? · unpaid invoices · Alle Zahlungen an Swisscom', style: 'width:100%' });
    var go = function () {
      if (!input.value.trim()) return;
      clear(out).appendChild(el('p', { class: 'muted', text: 'Thinking…' }));
      api('POST', '/ask', { question: input.value }).then(function (a) {
        clear(out).appendChild(el('div', { class: 'kpi', text: a.answer }));
        out.appendChild(el('p', { class: 'muted', text: 'Computed from your ledger, not by a language model.' }));
        if (a.items.length) out.appendChild(table([['Result'], ['Status']], a.items.map(function (i) { return el('tr', {}, [el('td', { text: i.label || '' }), el('td', {}, [i.verification ? status(i.verification) : ''])]); })));
      }).catch(function (e) { clear(out).appendChild(el('p', { text: e.message })); });
    };
    input.addEventListener('keydown', function (e) { if (e.key === 'Enter') go(); });
    v.appendChild(card('Ask', [input, out]));
    input.focus();
  }

  function renderPhone() {
    var v = clear(view()), qr = el('div', { class: 'grid', style: 'grid-template-columns:repeat(auto-fit,minmax(260px,1fr))' }), list = el('div');
    var start = el('button', { class: 'btn primary', text: 'Pair a phone', onclick: function () {
      clear(qr).appendChild(el('p', { class: 'muted', text: 'Starting the phone connection…' }));
      api('POST', '/ui/pair-phone').then(function (p) {
        clear(qr);
        var mk = function (title, text, svg) {
          var box = el('div', { class: 'qr' }); box.innerHTML = svg; // SVG generated by the service, not from documents
          return card(title, [el('p', { class: 'muted', text: text }), box]);
        };
        qr.appendChild(mk('1 · Install the app', 'Scan with the phone camera to download the Android app. Allow installing from your browser; if Play Protect asks, choose More details → Install anyway.', p.app_svg));
        qr.appendChild(mk('2 · Connect this phone', 'In the app tap “Scan pairing code”. Works once, for 5 minutes, on the same Wi-Fi.', p.pair_svg));
        qr.appendChild(card('3 · If the phone cannot connect', [
          el('p', { class: 'muted', text: 'The phone connects to this computer at ' + p.address + ':' + p.port + '. Both must be on the same Wi-Fi (not a guest network), and a VPN on either side can get in the way.' })]));
        firewallCard(p);
      }).catch(function (e) { clear(qr).appendChild(el('p', { text: e.message })); });
    } });
    v.appendChild(card('Phone', [el('p', { class: 'muted', text: 'Photograph and scan receipts with your Android phone; they arrive here while both are on the same Wi-Fi.' }), start, qr]));
    v.appendChild(card('Paired phones', [list]));
    api('GET', '/ui/phone-network').then(firewallCard).catch(function () {});
    api('GET', '/ui/phones').then(function (ps) {
      clear(list).appendChild(ps.length ? table([['Name'], ['Paired'], ['Last seen'], ['', 'r']], ps.map(function (p) {
        return el('tr', {}, [el('td', { text: p.name + (p.revoked_at ? ' (revoked)' : '') }), el('td', { text: String(p.paired_at).slice(0, 16) }),
          el('td', { text: p.last_seen_at ? String(p.last_seen_at).slice(0, 16) : '—' }),
          el('td', { class: 'r' }, [p.revoked_at ? '' : el('button', { class: 'btn small', text: 'Disconnect', onclick: function () {
            api('DELETE', '/ui/phones/' + p.id).then(renderPhone); } })])]);
      })) : el('p', { class: 'muted', text: 'No phone paired yet.' }));
    });
  }

  function firewallCard(net) {
    if (!net.windows || net.firewall_ok) return;
    var box = document.getElementById('fw-card'); if (box) box.remove();
    var msg = el('p', { class: 'muted', text: 'Windows Firewall blocks phones until you allow it once. Windows will ask for confirmation (an administrator password if you are not one).' });
    box = card('Windows Firewall', [msg, el('button', { class: 'btn primary', text: 'Allow phones on this Wi-Fi', onclick: function () {
      api('POST', '/ui/phone-firewall').then(function (r) {
        msg.textContent = r.started ? 'Confirm in the Windows prompt. Checking…' : 'Windows did not start the change.';
        var tries = 0, check = function () {
          api('GET', '/ui/phone-network').then(function (n) {
            if (n.firewall_ok) { msg.textContent = '✓ Phones on this Wi-Fi are allowed. Try pairing again.'; }
            else if (++tries < 20) setTimeout(check, 1500);
            else msg.textContent = 'Not allowed yet. Press the button again and choose “Yes” in the Windows prompt.';
          });
        };
        setTimeout(check, 1500);
      }).catch(function (x) { msg.textContent = x.message; });
    } })]);
    box.id = 'fw-card';
    view().insertBefore(box, view().firstChild);
  }

  var aiTimer = null;
  function updateAIPill(s) {
    var p = document.getElementById('ai-pill'); if (!p) return;
    var label = { not_installed: 'AI: not installed', off: 'AI: off', starting: 'AI: starting…', on: 'AI: on', error: 'AI: not running' }[s.state] || 'AI';
    p.textContent = label; p.className = 'ai-pill ' + s.state; p.hidden = false;
    clearTimeout(aiTimer);
    aiTimer = setTimeout(refreshAI, s.state === 'starting' || (s.progress && s.progress.running) ? 3000 : 30000);
  }
  function refreshAI() { api('GET', '/ui/ai').then(updateAIPill).catch(function () {}); }

  function renderSettings() {
    var v = clear(view()), ai = el('div'), sec = el('div');
    v.appendChild(card('Local AI (Apertus)', [ai]));
    v.appendChild(card('Export', [el('p', { class: 'muted', text: 'Everything: every table as JSON and CSV, all originals, a SHA-256 manifest.' }),
      el('button', { class: 'btn', text: 'Download full archive', onclick: function () {
        toast('Preparing the archive…');
        api('POST', '/export', undefined, true).then(function (r) { return r.blob(); }).then(function (b) {
          var a = el('a', { href: URL.createObjectURL(b), download: 'financial-lens-export.zip' }); document.body.appendChild(a); a.click(); a.remove();
        }).catch(function (e) { toast(e.message); });
      } })]));
    v.appendChild(card('Security check', [sec]));
    var about = el('div');
    v.appendChild(card('About', [about]));
    api('GET', '/ui/about').then(function (a) {
      about.appendChild(el('p', { class: 'kpi', text: 'Financial Lens ' + a.version }));
      about.appendChild(el('details', { open: 'open' }, [el('summary', { text: 'What’s new' }), markdown(a.changelog)]));
    }).catch(function () {});
    var drawAI = function () {
      api('GET', '/ui/ai').then(function (s) {
        clear(ai);
        updateAIPill(s);
        var head = { not_installed: '○ Not installed', off: '○ Installed, switched off', starting: '◌ Starting… (up to a minute)',
          on: '● On: Apertus is reading your documents', error: '⚠ Not running' }[s.state] || s.state;
        ai.appendChild(el('p', { class: 'ai-state ' + s.state, text: head }));
        if (s.state === 'error' && s.error) ai.appendChild(el('p', { class: 'muted', text: s.error }));
        if (s.progress && s.progress.running) {
          var bar = el('div', { class: 'bar-progress' }, [el('div', { style: 'width:' + Math.round((s.progress.frac || 0) * 100) + '%' })]);
          ai.appendChild(el('p', { text: (s.progress.label || '') + ' ' + Math.round((s.progress.frac || 0) * 100) + ' %' }));
          ai.appendChild(bar);
          ai.appendChild(el('button', { class: 'btn small', text: 'Cancel', onclick: function () { api('POST', '/ui/ai/cancel'); } }));
          setTimeout(drawAI, 700);
          return;
        }
        if (s.progress && s.progress.error) ai.appendChild(el('p', { text: s.progress.error }));
        if (s.state === 'not_installed') {
          ai.appendChild(el('button', { class: 'btn primary', text: 'Download and switch on', onclick: function () { api('POST', '/ui/ai/install').then(function () { setTimeout(drawAI, 300); }); } }));
        } else if (s.state === 'starting') {
          setTimeout(drawAI, 2000);
        } else {
          var on = s.state === 'on';
          ai.appendChild(el('button', { class: 'btn ' + (on ? '' : 'primary'), text: on ? 'Switch off' : (s.state === 'error' ? 'Try again' : 'Switch on'), onclick: function () {
            api('POST', '/ui/ai/toggle', { on: !on }).then(drawAI).catch(function (e) { toast(e.message); });
          } }));
        }
        if ((s.models || []).length > 1 && !(s.progress && s.progress.running)) {
          ai.appendChild(el('h4', { text: 'Model' }));
          if (s.gpu) ai.appendChild(el('p', { class: 'muted', text: 'Graphics card: ' + s.gpu.name + ' · ' + s.gpu.vram_gb + ' GB video memory' }));
          s.models.forEach(function (m) {
            var pick = m.selected ? el('span', { class: 'st confirmed', text: m.installed ? '● in use' : '● chosen' }) : el('button', { class: 'btn small' + (m.role === 'analyst' && m.fits !== false ? ' primary' : ''),
              text: m.installed ? 'Use this' : 'Download (' + (m.size_bytes / 1e9).toFixed(1) + ' GB) and use', onclick: function () {
                if (m.fits === false && !confirm('This computer’s graphics card seems too small for ' + m.name + '. It will run, but slowly. Continue?')) return;
                api('POST', '/ui/ai/install', { model: m.key }).then(function () { setTimeout(drawAI, 400); }).catch(function (e) { toast(e.message); });
              } });
            ai.appendChild(el('div', { class: 'model-row' }, [el('div', {}, [el('strong', { text: m.name }),
              el('div', { class: 'muted small', text: (m.role === 'analyst' ? 'Reads every document as a whole: merchant, each item, VAT, total, category; the program checks its arithmetic. Needs ' : 'Helps when the rules are unsure. Runs on ') + m.needs + '.' })]), pick]));
          });
        }
        ai.appendChild(el('p', { class: 'muted', text: s.model + ' · ' + s.licence + ' · about ' + (s.size_bytes / 1e9).toFixed(1) + ' GB, runs on this computer only. ' +
          'When it is on, new documents are read with it where the rules are unsure; its reading counts only if the arithmetic reconciles. ' +
          'Documents added before can be read again from Uploads → Read again.' }));
      });
    };
    drawAI();
    api('GET', '/security/check').then(function (r) {
      clear(sec).appendChild(table([['Check'], ['Result']], r.checks.map(function (c) { return el('tr', {}, [el('td', { text: (c.ok ? '✓ ' : '⚠ ') + c.check }), el('td', { class: 'muted', text: c.detail })]); })));
    }).catch(function (e) { clear(sec).appendChild(el('p', { class: 'muted', text: e.message })); });
  }


  // ------------------------------------------------------------ version and what's new
  var ABOUT = null;
  function markdown(md) {
    // the changelog ships with the app; rendered as text nodes (headings, bullets, **bold**)
    var box = el('div', { class: 'md' }), ul = null;
    var inline = function (line, node) {
      line.split(/(\*\*[^*]+\*\*)/).forEach(function (part) {
        if (/^\*\*[^*]+\*\*$/.test(part)) node.appendChild(el('strong', { text: part.slice(2, -2) }));
        else if (part) node.appendChild(document.createTextNode(part));
      });
      return node;
    };
    md.split('\n').forEach(function (raw) {
      var line = raw.replace(/\s+$/, '');
      if (/^#\s/.test(line)) return;
      if (/^##\s/.test(line)) { ul = null; box.appendChild(el('h4', { text: line.replace(/^##\s*/, '') })); return; }
      if (/^- /.test(line)) { if (!ul) { ul = el('ul'); box.appendChild(ul); } ul.appendChild(inline(line.slice(2), el('li'))); return; }
      if (/^\s+\S/.test(line) && ul && ul.lastChild) { ul.lastChild.appendChild(document.createTextNode(' ')); inline(line.trim(), ul.lastChild); return; }
      if (line) { ul = null; box.appendChild(inline(line, el('p'))); }
    });
    return box;
  }
  function section(md, version) {
    var parts = md.split(/^## /m), hit = parts.find(function (p) { return p.indexOf(version) === 0; });
    return hit ? '## ' + hit : '';
  }
  function whatsNewOnce(a) {
    var seen = null;
    try { seen = localStorage.getItem('fl-seen-version'); } catch (e) { return; }
    try { localStorage.setItem('fl-seen-version', a.version); } catch (e) { return; }
    if (!seen || seen === a.version) return;  // first start ever, or nothing new
    var notes = section(a.changelog, a.version); if (!notes) return;
    var d = el('dialog', { class: 'nag', 'aria-labelledby': 'wn-title' }, [el('h2', { id: 'wn-title', text: 'What’s new in ' + a.version }), markdown(notes),
      el('div', { class: 'nag-actions' }, [el('button', { class: 'btn primary', text: 'OK', onclick: function () { d.close(); d.remove(); } })])]);
    document.body.appendChild(d); if (d.showModal) d.showModal();
  }

  // ------------------------------------------------------------ corporate edition
  var ME = null;
  function field(label, input) { return el('label', {}, [label, input]); }
  function input(type, attrs) { return el('input', Object.assign({ type: type }, attrs || {})); }
  function signOut() { api('POST', '/ui/logout').then(function () { location.hash = '#/overview'; location.reload(); }); }

  function renderLogin(needsSetup, msg) {
    document.body.classList.add('signed-out');
    var v = clear(view()), err = el('p', { class: 'muted', text: msg || '' });
    var login = input('text', { autocomplete: 'username', required: 'required' }), pw = input('password', { autocomplete: needsSetup ? 'new-password' : 'current-password' });
    var code = input('text', { placeholder: 'XXXX-XXXX-XXXX-XXXX' }), name = input('text', { autocomplete: 'name' });
    var go = function (e) {
      e.preventDefault();
      var req = needsSetup ? api('POST', '/ui/setup', { code: code.value, login: login.value, name: name.value, password: pw.value })
        : api('POST', '/ui/login', { login: login.value, password: pw.value });
      req.then(function (j) { CSRF = j.csrf; document.body.classList.remove('signed-out'); location.hash = '#/overview'; start(); })
        .catch(function (x) { err.textContent = x.message; });
    };
    var kids = needsSetup
      ? [el('h2', { text: 'Create the first administrator' }),
         el('p', { class: 'muted', text: 'The setup code is printed in the server console and its log at start. It works once.' }),
         field('Setup code', code), field('Your name', name), field('Login', login), field('Password (at least 10 characters)', pw)]
      : [el('h2', { text: 'Sign in to Financial Lens' }), field('Login', login), field('Password', pw)];
    var form = el('form', { class: 'card login', onsubmit: go }, kids.concat([el('button', { class: 'btn primary', type: 'submit', text: needsSetup ? 'Create and sign in' : 'Sign in' }), err]));
    v.appendChild(form);
    (needsSetup ? code : login).focus();
  }

  function licenceBanner(lic) {
    var b = document.getElementById('licence-banner');
    if (!lic) { b.hidden = true; return; }
    var admin = ME && (ME.role === 'owner' || ME.role === 'admin');
    var text = '';
    if (lic.state === 'trial' && lic.days_left <= 30) text = 'Trial: ' + lic.days_left + ' days left. ';
    else if (lic.state === 'active' && lic.days_left <= 30) text = 'The licence ends in ' + lic.days_left + ' days. ';
    else if (lic.nag) text = (lic.message || 'A licence key is needed.') + ' ';
    b.hidden = !text; b.className = 'banner' + (lic.nag ? ' warn' : '');
    clear(b).appendChild(document.createTextNode(text));
    if (text && admin) b.appendChild(el('a', { href: '#/license', text: 'Get a licence key' }));
  }


  // After the trial (or when a licence ended) a reminder keeps coming back until a key is installed.
  var NAG_EVERY = 15 * 60 * 1000, nagTimer = null;
  function showNag(lic) {
    var old = document.getElementById('nag'); if (old) old.remove();
    var admin = ME && (ME.role === 'owner' || ME.role === 'admin');
    var close = function () { d.close(); d.remove(); };
    var mail = 'mailto:' + lic.contact + '?subject=' + encodeURIComponent('Financial Lens subscription') +
      '&body=' + encodeURIComponent('We would like a subscription for ' + Math.max(lic.users || 1, 1) + ' users.\nPlan (monthly or 2 years): \n');
    var d = el('dialog', { id: 'nag', class: 'nag', 'aria-labelledby': 'nag-title' }, [
      el('h2', { id: 'nag-title', text: lic.state === 'trial_ended' ? 'Your free trial has ended' : 'Your licence needs attention' }),
      el('p', { text: lic.message || '' }),
      el('p', { class: 'muted', text: 'CHF 1 per user per month, or CHF 10 per user for 2 years' +
        (lic.prices ? ' (for your ' + Math.max(lic.users || 1, 1) + ' users: CHF ' + lic.prices.monthly + ' per month or CHF ' + lic.prices['2y'] + ' for 2 years).' : '.') }),
      el('div', { class: 'nag-actions' }, [
        el('a', { class: 'btn primary', href: mail, text: 'Buy a subscription' }),
        admin ? el('a', { class: 'btn', href: '#/license', text: 'Enter licence key', onclick: close }) : null,
        el('button', { class: 'btn', type: 'button', text: 'Remind me later', onclick: close })]),
      admin ? null : el('p', { class: 'muted', text: 'Your administrator can enter the key under Licence.' })]);
    document.body.appendChild(d);
    if (d.showModal) d.showModal(); else d.setAttribute('open', '');
  }
  function startNag(lic) {
    clearInterval(nagTimer);
    if (!lic || !lic.nag) return;
    showNag(lic);
    nagTimer = setInterval(function () { showNag(lic); }, NAG_EVERY);
  }

  function renderTeam() {
    var v = clear(view()), list = el('div', { class: 'scroll' }), err = el('p', { class: 'muted' });
    var login = input('text'), name = input('text'), email = input('email'), pw = input('password', { autocomplete: 'new-password' }), role = el('select');
    var add = el('form', { class: 'form', onsubmit: function (e) {
      e.preventDefault();
      api('POST', '/ui/users', { login: login.value, name: name.value, email: email.value, role: role.value, password: pw.value })
        .then(function () { toast('Created ' + login.value + '. Give them the password in person.'); renderTeam(); })
        .catch(function (x) { err.textContent = x.message; });
    } }, [field('Name', name), field('Login', login), field('E-mail (for single sign-on)', email), field('Role', role),
      field('First password', pw), el('button', { class: 'btn primary', type: 'submit', text: 'Add person' })]);
    v.appendChild(card('People', [list]));
    v.appendChild(card('Add a person', [add, err]));
    api('GET', '/ui/users').then(function (d) {
      d.roles.forEach(function (r) { role.appendChild(el('option', { value: r.id, text: r.label })); });
      role.value = 'viewer';
      var seats = d.seats ? d.active + ' of ' + d.seats + ' licensed users' : d.active + ' active users';
      clear(list).appendChild(el('p', { class: 'muted', text: seats }));
      list.appendChild(table([['Name'], ['Login'], ['Role'], ['Last sign-in'], ['', 'r']], d.users.map(function (u) {
        var sel = el('select', { 'aria-label': 'Role of ' + u.name });
        d.roles.forEach(function (r) { sel.appendChild(el('option', { value: r.id, text: r.label })); });
        sel.value = u.role; if (u.id === d.me) sel.disabled = true;
        sel.addEventListener('change', function () {
          api('PATCH', '/ui/users/' + u.id, { role: sel.value }).then(function () { toast('Role changed.'); }).catch(function (x) { toast(x.message); sel.value = u.role; });
        });
        var acts = el('td', { class: 'r' });
        if (u.id !== d.me) {
          acts.appendChild(el('button', { class: 'btn small', text: 'Reset password', onclick: function () {
            var p = window.prompt('New password for ' + u.login + ' (at least 10 characters):');
            if (p) api('PATCH', '/ui/users/' + u.id, { password: p }).then(function () { toast('Password reset; their sessions ended.'); }).catch(function (x) { toast(x.message); });
          } }));
          acts.appendChild(document.createTextNode(' '));
          acts.appendChild(el('button', { class: 'btn small', text: u.disabled_at ? 'Enable' : 'Disable', onclick: function () {
            api('PATCH', '/ui/users/' + u.id, { disabled: !u.disabled_at }).then(renderTeam).catch(function (x) { toast(x.message); });
          } }));
        }
        return el('tr', {}, [el('td', { text: u.name + (u.disabled_at ? ' (disabled)' : '') }), el('td', { text: u.login }), el('td', {}, [sel]),
          el('td', { class: 'muted', text: u.last_login_at ? String(u.last_login_at).slice(0, 16).replace('T', ' ') : '—' }), acts]);
      })));
    }).catch(function (x) { clear(list).appendChild(el('p', { text: x.message })); });
  }

  function renderAudit() {
    var v = clear(view()), out = el('div', { class: 'scroll' }), who = input('search', { placeholder: 'Person' }), what = el('select');
    var load = function () {
      var q = '/ui/audit?limit=500' + (who.value ? '&actor=' + encodeURIComponent(who.value) : '') + (what.value ? '&action=' + encodeURIComponent(what.value) : '');
      api('GET', q).then(function (d) {
        if (what.options.length <= 1) d.actions.forEach(function (a) { what.appendChild(el('option', { value: a, text: a })); });
        clear(out).appendChild(el('p', { class: d.chain.ok ? 'st confirmed' : 'st needs_review',
          text: d.chain.ok ? '● Chain intact: ' + d.chain.checked + ' entries verified, none changed or removed.' : '● Chain broken at entry ' + d.chain.broken_at + '.' }));
        out.appendChild(table([['When'], ['Who'], ['What'], ['Details']], d.entries.map(function (e) {
          return el('tr', {}, [el('td', { class: 'num', text: String(e.at).slice(0, 19).replace('T', ' ') }),
            el('td', { text: e.actor_name ? e.actor_name + ' (' + e.actor_login + ')' : e.actor }),
            el('td', { text: e.action + ' · ' + e.entity }), el('td', { class: 'muted mono', text: JSON.stringify(e.details) })]);
        })));
      }).catch(function (x) { clear(out).appendChild(el('p', { text: x.message })); });
    };
    what.appendChild(el('option', { value: '', text: 'All actions' }));
    who.addEventListener('change', load); what.addEventListener('change', load);
    v.appendChild(card('Audit log', [el('div', { class: 'form' }, [field('Person', who), field('Action', what),
      el('a', { class: 'btn', href: '/ui/audit.csv', text: 'Download CSV' })]), out]));
    load();
  }

  function renderLicense() {
    var v = clear(view()), box = el('div'), key = el('textarea', { placeholder: 'FLK1.…', 'aria-label': 'Licence key' }), err = el('p', { class: 'muted' });
    v.appendChild(card('Licence', [box]));
    v.appendChild(card('Install a licence key', [key, el('button', { class: 'btn primary', text: 'Install key', onclick: function () {
      api('POST', '/ui/license', { key: key.value }).then(function () { toast('Licence installed.'); start(); }).catch(function (x) { err.textContent = x.message; });
    } }), err]));
    api('GET', '/ui/license').then(function (l) {
      var state = { trial: 'Trial', active: 'Licensed', trial_ended: 'Trial ended (read-only)', expired: 'Licence ended (read-only)',
        over_seats: 'More users than licensed (read-only)', invalid: 'Key not valid (read-only)' }[l.state] || l.state;
      var dl = el('dl');
      [['Status', state], ['Trial', l.trial_started + ' – ' + l.trial_ends],
        ['Licensed to', l.customer || '—'], ['Users', l.users + (l.seats ? ' of ' + l.seats : '')], ['Valid until', l.expires || (l.state === 'trial' ? l.trial_ends : '—')]]
        .forEach(function (p) { dl.appendChild(el('dt', { text: p[0] })); dl.appendChild(el('dd', { text: p[1] })); });
      clear(box).appendChild(el('div', { class: 'ev' }, [dl]));
      if (l.message) box.appendChild(el('p', { text: l.message }));
      box.appendChild(el('h4', { text: 'Prices for ' + Math.max(l.users, 1) + ' users' }));
      box.appendChild(el('p', { text: 'CHF 1 per user per month (CHF ' + l.prices.monthly + ' per month), or CHF 10 per user for 2 years (CHF ' + l.prices['2y'] + ').' }));
      if (l.request) {
        box.appendChild(el('h4', { text: 'Request a key' }));
        box.appendChild(el('p', { class: 'muted', text: 'Send this request code, the plan you want and the number of users to Helvetic Lens (' + l.contact + '). The key you receive works on this server only, and is checked here without any internet connection.' }));
        var code = el('div', { class: 'ev' }, [el('code', { class: 'mono', text: l.request })]);
        box.appendChild(code);
        box.appendChild(el('button', { class: 'btn small', text: 'Copy request code', onclick: function () {
          if (navigator.clipboard) navigator.clipboard.writeText(l.request).then(function () { toast('Copied.'); });
        } }));
        if (l.contact.indexOf('@') > 0) {
          box.appendChild(document.createTextNode(' '));
          box.appendChild(el('a', { class: 'btn small', text: 'E-mail the request', href: 'mailto:' + l.contact +
            '?subject=' + encodeURIComponent('Financial Lens licence request') +
            '&body=' + encodeURIComponent('Plan (monthly or 2 years): \nNumber of users: ' + Math.max(l.users, 1) + '\nCompany: ' + (l.customer || '') + '\n\nRequest code:\n' + l.request) }));
        }
      }
    }).catch(function (x) { clear(box).appendChild(el('p', { text: x.message })); });
  }

  function renderAccount() {
    var v = clear(view()), cur = input('password', { autocomplete: 'current-password' }), pw = input('password', { autocomplete: 'new-password' }), err = el('p', { class: 'muted' });
    v.appendChild(card('My account', [el('p', { text: (ME.name || '') + ' · ' + ME.login + ' · ' + ME.role }),
      el('form', { class: 'form', onsubmit: function (e) {
        e.preventDefault();
        api('POST', '/ui/password', { current: cur.value, password: pw.value }).then(function () { toast('Password changed. Please sign in again.'); setTimeout(function () { location.reload(); }, 1200); })
          .catch(function (x) { err.textContent = x.message; });
      } }, [field('Current password', cur), field('New password (at least 10 characters)', pw), el('button', { class: 'btn', type: 'submit', text: 'Change password' })]), err,
      el('button', { class: 'btn', text: 'Sign out', onclick: signOut })]));
  }

  // ------------------------------------------------------------ upload
  function rereadButton(id, after) {
    return el('button', { class: 'btn small', text: 'Read again', onclick: function (e) {
      var b = e.target; b.disabled = true; b.textContent = 'Reading…';
      api('POST', '/documents/' + id + '/reread').then(function (r) {
        toast((r.doc_type || '') + ': ' + r.operation_ids.length + ' record(s). ' + (r.messages || []).join(' '), 10000);
        if (after) after(); refreshInboxCount();
      }).catch(function (x) { b.disabled = false; b.textContent = 'Read again'; toast(x.message, 10000); });
    } });
  }
  function upload(files) {
    if (!files.length) return;
    var fd = new FormData(), names = [];
    Array.prototype.forEach.call(files, function (f) { fd.append('files', f, f.name); names.push(f.name); });
    toast('Reading ' + files.length + ' file(s)…', 120000);
    api('POST', '/documents', fd).then(function (res) {
      document.getElementById('toast').hidden = true;
      route(); refreshInboxCount();
      var old = document.getElementById('upload-result'); if (old) old.remove();
      var rows = res.map(function (r, i) {
        var what = r.duplicate_of && !r.operation_ids.length ? 'Already here (added earlier)' : r.duplicate_of ? 'Already recorded; file attached' : r.operation_ids.length ? r.operation_ids.length + ' record(s): ' + r.doc_type : 'Waits for review: ' + r.doc_type;
        return el('tr', {}, [el('td', { text: names[i] || '' }), el('td', { text: what }), el('td', { class: 'muted', text: (r.messages || []).join(' ') }),
          el('td', { class: 'r' }, [el('a', { class: 'btn small', href: '#/upload/' + r.document_id, text: 'Open' }), ' ',
            !r.operation_ids.length ? rereadButton(r.document_id, function () { route(); }) : null])]);
      });
      var box = card('Just added', [table([['File'], ['Result'], ['Note'], ['', 'r']], rows),
        el('p', { class: 'muted', text: 'A file that is already here is not added twice. “Read again” reads it once more, with the local AI if it is on.' }),
        el('button', { class: 'btn small', text: 'Close', onclick: function () { box.remove(); } })]);
      box.id = 'upload-result';
      setTimeout(function () { view().insertBefore(box, view().firstChild); }, 300);
    }).catch(function (e) { toast(e.message); });
  }

  // ------------------------------------------------------------ routing
  var PAGES = { overview: renderOverview, inbox: renderInbox, documents: renderDocuments, upload: renderUpload, transactions: renderTransactions,
    analytics: renderAnalytics, ask: renderAsk, phone: renderPhone, settings: renderSettings,
    team: renderTeam, audit: renderAudit, license: renderLicense, account: renderAccount };
  function route() {
    var page = (location.hash.replace(/^#\/?/, '').split('/')[0]) || 'overview';
    if (!PAGES[page]) page = 'overview';
    if (ME && ME.role === 'member' && page !== 'account') { location.hash = '#/account'; return; }
    document.querySelectorAll('[data-nav]').forEach(function (a) { a.classList.toggle('on', a.getAttribute('data-nav') === (page === 'upload' ? 'documents' : page)); });
    PAGES[page]();
  }
  function refreshInboxCount() {
    api('GET', '/ui/inbox').then(function (d) {
      var n = d.links.length + d.review.length, p = document.getElementById('inbox-count');
      p.hidden = !n; p.textContent = String(n);
    }).catch(function () {});
  }

  var started = false;
  function start() {
    if (started) { boot(); return; }
    started = true;
    ['period', 'mode', 'group'].forEach(function (id) {
      var s = document.getElementById(id);
      try { var saved = localStorage.getItem('fl-' + id); if (saved) s.value = saved; } catch (e) { /* no storage */ }
      state[id] = s.value;
      s.addEventListener('change', function () { state[id] = s.value; state.path = []; try { localStorage.setItem('fl-' + id, s.value); } catch (e) {} route(); });
    });
    document.getElementById('file-input').addEventListener('change', function (e) { upload(e.target.files); e.target.value = ''; });
    var drop = document.getElementById('drop'), depth = 0;
    window.addEventListener('dragenter', function (e) { if (e.dataTransfer && Array.prototype.indexOf.call(e.dataTransfer.types, 'Files') >= 0) { depth++; drop.hidden = false; } });
    window.addEventListener('dragleave', function () { if (--depth <= 0) { depth = 0; drop.hidden = true; } });
    window.addEventListener('dragover', function (e) { e.preventDefault(); });
    window.addEventListener('drop', function (e) { e.preventDefault(); depth = 0; drop.hidden = true; upload(e.dataTransfer.files); });
    window.addEventListener('hashchange', route);
    var t = null;
    window.addEventListener('resize', function () { clearTimeout(t); t = setTimeout(function () { if ((location.hash || '#/overview').indexOf('overview') >= 0 && state.tree) renderOverview(); }, 200); });
    boot();
  }
  function boot() {
    api('GET', '/ui/me').then(function (me) {
      CSRF = me.csrf;
      var org = (me.organizations || []).find(function (o) { return o.id === me.org; });
      var foot = clear(document.getElementById('side-foot'));
      foot.appendChild(document.createTextNode((org ? org.name : '') + ' · ' + { local_only: 'L2 local only', swiss_hosted: 'L1 Swiss', cloud_ai: 'L0' }[me.privacy]));
      foot.appendChild(el('br'));
      var ver = el('a', { href: '#/settings', class: 'ver', text: 'Version …' }); foot.appendChild(ver);
      api('GET', '/ui/about').then(function (a) { ABOUT = a; ver.textContent = 'Version ' + a.version + ' · What’s new'; whatsNewOnce(a); }).catch(function () {});
      if (me.edition === 'corporate') {
        ME = me.user;
        var admin = ME.role === 'owner' || ME.role === 'admin';
        document.querySelectorAll('[data-corp]').forEach(function (a) { a.hidden = a.getAttribute('data-corp') === 'admin' && !admin; });
        if (ME.role === 'member') document.querySelectorAll('[data-nav]').forEach(function (a) { if (a.getAttribute('data-nav') !== 'account') a.hidden = true; });
        foot.appendChild(el('br'));
        foot.appendChild(document.createTextNode(ME.name + ' · '));
        foot.appendChild(el('button', { type: 'button', text: 'Sign out', onclick: signOut }));
        licenceBanner(me.license);
        startNag(me.license);
      }
      route(); if (!ME || ME.role !== 'member') { refreshInboxCount(); refreshAI(); }
    }).catch(function (e) {
      fetch('/ui/edition', { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (ed) {
        if (ed.edition === 'corporate') renderLogin(ed.needs_setup);
        else clear(view()).appendChild(el('p', { class: 'empty', text: e.message }));
      }).catch(function () { clear(view()).appendChild(el('p', { class: 'empty', text: e.message })); });
    });
  }

  // The launch URL carries the key in the fragment (never sent to a server log); exchange it for a cookie.
  var m = /k=([A-Za-z0-9_\-]+)/.exec(location.hash);
  if (m) {
    history.replaceState(null, '', location.pathname + '#/overview');
    fetch('/ui/session', { method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin', body: JSON.stringify({ key: m[1] }) })
      .then(function (r) { return r.json(); }).then(function (j) { CSRF = j.csrf || ''; start(); });
  } else {
    start();
  }
})();
