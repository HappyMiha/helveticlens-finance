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
          return el('tr', {}, [el('td', { text: r.op_date }), el('td', { text: r.kind }), el('td', { text: r.counterparty }), el('td', { text: r.category }),
            el('td', { class: 'r num', text: chf(r.amount) }), el('td', {}, [status(r.verification)])]);
        })) : el('p', { class: 'empty', text: 'No records in this period.' })]));
    }).catch(function (e) { toast(e.message); });
  }

  function renderDocuments() {
    var v = clear(view());
    api('GET', '/documents').then(function (docs) {
      v.appendChild(card('Documents · ' + docs.length, [docs.length ? table([['Received'], ['File'], ['Type'], ['Status'], ['Folder'], ['Records', 'r']],
        docs.map(function (d) {
          return el('tr', {}, [el('td', { text: String(d.received_at).slice(0, 16).replace('T', ' ') }),
            el('td', {}, [el('a', { href: '/documents/' + d.id + '/original', target: '_blank', rel: 'noopener', text: d.filename })]),
            el('td', { text: d.doc_type }), el('td', { text: d.processing_status }), el('td', { class: 'muted', text: d.folder || '' }),
            el('td', { class: 'r', text: String(d.operations) })]);
        })) : el('p', { class: 'empty', text: 'No documents yet. Drop files anywhere on this page.' })]));
    }).catch(function (e) { toast(e.message); });
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
      }).catch(function (e) { clear(qr).appendChild(el('p', { text: e.message })); });
    } });
    v.appendChild(card('Phone', [el('p', { class: 'muted', text: 'Photograph and scan receipts with your Android phone; they arrive here while both are on the same Wi-Fi.' }), start, qr]));
    v.appendChild(card('Paired phones', [list]));
    api('GET', '/ui/phones').then(function (ps) {
      clear(list).appendChild(ps.length ? table([['Name'], ['Paired'], ['Last seen'], ['', 'r']], ps.map(function (p) {
        return el('tr', {}, [el('td', { text: p.name + (p.revoked_at ? ' (revoked)' : '') }), el('td', { text: String(p.paired_at).slice(0, 16) }),
          el('td', { text: p.last_seen_at ? String(p.last_seen_at).slice(0, 16) : '—' }),
          el('td', { class: 'r' }, [p.revoked_at ? '' : el('button', { class: 'btn small', text: 'Disconnect', onclick: function () {
            api('DELETE', '/ui/phones/' + p.id).then(renderPhone); } })])]);
      })) : el('p', { class: 'muted', text: 'No phone paired yet.' }));
    });
  }

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
    var drawAI = function () {
      api('GET', '/ui/ai').then(function (s) {
        clear(ai);
        ai.appendChild(el('p', { class: 'muted', text: s.model + ' · ' + s.licence + ' · about ' + (s.size_bytes / 1e9).toFixed(1) + ' GB. Asked only when the rules are unsure; its reading counts only if the arithmetic reconciles. Runs on this computer only.' }));
        var installed = s.model_installed && s.runtime_installed;
        if (s.progress && s.progress.running) {
          var bar = el('div', { class: 'bar-progress' }, [el('div', { style: 'width:' + Math.round((s.progress.frac || 0) * 100) + '%' })]);
          ai.appendChild(el('p', { text: (s.progress.label || '') + ' ' + Math.round((s.progress.frac || 0) * 100) + ' %' }));
          ai.appendChild(bar);
          ai.appendChild(el('button', { class: 'btn small', text: 'Cancel', onclick: function () { api('POST', '/ui/ai/cancel'); } }));
          setTimeout(drawAI, 700);
          return;
        }
        if (s.progress && s.progress.error) ai.appendChild(el('p', { text: s.progress.error }));
        if (!installed) {
          ai.appendChild(el('button', { class: 'btn primary', text: 'Download and enable', onclick: function () { api('POST', '/ui/ai/install').then(function () { setTimeout(drawAI, 300); }); } }));
        } else {
          ai.appendChild(el('button', { class: 'btn ' + (s.enabled ? '' : 'primary'), text: s.enabled ? 'Turn AI assist off' : 'Turn AI assist on', onclick: function () {
            toast(s.enabled ? 'Stopping…' : 'Starting the model…');
            api('POST', '/ui/ai/toggle', { on: !s.enabled }).then(function (r) { toast(r.enabled ? 'AI assist is on.' : 'AI assist is off.'); drawAI(); }).catch(function (e) { toast(e.message); });
          } }));
        }
      });
    };
    drawAI();
    api('GET', '/security/check').then(function (r) {
      clear(sec).appendChild(table([['Check'], ['Result']], r.checks.map(function (c) { return el('tr', {}, [el('td', { text: (c.ok ? '✓ ' : '⚠ ') + c.check }), el('td', { class: 'muted', text: c.detail })]); })));
    }).catch(function (e) { clear(sec).appendChild(el('p', { class: 'muted', text: e.message })); });
  }

  // ------------------------------------------------------------ upload
  function upload(files) {
    if (!files.length) return;
    var fd = new FormData();
    Array.prototype.forEach.call(files, function (f) { fd.append('files', f, f.name); });
    toast('Reading ' + files.length + ' file(s)…', 60000);
    api('POST', '/documents', fd).then(function (res) {
      toast(res.map(function (r) { return (r.doc_type || '?') + ': ' + r.operation_ids.length + ' record(s). ' + (r.messages || []).join(' '); }).join('\n'), 12000);
      route(); refreshInboxCount();
    }).catch(function (e) { toast(e.message); });
  }

  // ------------------------------------------------------------ routing
  var PAGES = { overview: renderOverview, inbox: renderInbox, documents: renderDocuments, transactions: renderTransactions,
    analytics: renderAnalytics, ask: renderAsk, phone: renderPhone, settings: renderSettings };
  function route() {
    var page = (location.hash.replace(/^#\/?/, '').split('/')[0]) || 'overview';
    if (!PAGES[page]) page = 'overview';
    document.querySelectorAll('[data-nav]').forEach(function (a) { a.classList.toggle('on', a.getAttribute('data-nav') === page); });
    PAGES[page]();
  }
  function refreshInboxCount() {
    api('GET', '/ui/inbox').then(function (d) {
      var n = d.links.length + d.review.length, p = document.getElementById('inbox-count');
      p.hidden = !n; p.textContent = String(n);
    }).catch(function () {});
  }

  function start() {
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
    api('GET', '/ui/me').then(function (me) {
      CSRF = me.csrf;
      var org = (me.organizations || []).find(function (o) { return o.id === me.org; });
      document.getElementById('side-foot').textContent = (org ? org.name : '') + ' · ' + { local_only: 'L2 local only', swiss_hosted: 'L1 Swiss', cloud_ai: 'L0' }[me.privacy];
      route(); refreshInboxCount();
    }).catch(function (e) { clear(view()).appendChild(el('p', { class: 'empty', text: e.message })); });
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
