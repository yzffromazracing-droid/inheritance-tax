(function () {
  "use strict";

  var PAGE_SIZE = 50;
  // 種別コード → 表示名
  var TYPES = {
    kihon: { label: "相続税法基本通達", short: "基本通達" },
    hyoka: { label: "財産評価基本通達", short: "評価通達" },
    so: { label: "措置法通達", short: "措置法通達" },
    kobetsu: { label: "個別通達", short: "個別通達" },
    ta: { label: "タックスアンサー", short: "タックスアンサー" },
    qa: { label: "質疑応答事例", short: "質疑応答事例" },
    bk: { label: "文書回答事例", short: "文書回答事例" },
  };
  var TSUTATSU = { kihon: true, hyoka: true, so: true, kobetsu: true };
  var TABS = ["dict", "sozoku", "zoyo", "zaisan", "nta", "tsu"];
  var DICT_TABS = ["sozoku", "zoyo", "zaisan"];
  // サブタブのあるタブ（先頭が既定）
  var SUBS = { nta: ["ta", "qa", "bk"], tsu: ["kihon", "hyoka", "so", "kobetsu"] };
  // 種別ごとの掲載先（タブ・サブタブ）
  var HOME = {
    kihon: { tab: "tsu", sub: "kihon" },
    hyoka: { tab: "tsu", sub: "hyoka" },
    so: { tab: "tsu", sub: "so" },
    kobetsu: { tab: "tsu", sub: "kobetsu" },
    ta: { tab: "nta", sub: "ta" },
    qa: { tab: "nta", sub: "qa" },
    bk: { tab: "nta", sub: "bk" },
  };
  var REF_PREVIEW = 8; // テーマで出典ごとに最初に表示する件数
  var INSTANCES = {};

  var ARTICLES = [];
  var ARTICLES_BY_ID = {};
  var BY_URL = {};
  var BY_NUM = {};
  var BUNRUI = {}; // { タブ: { 区分key: 区分 } }
  var TAB_LABEL = {}; // { タブ: 表示名 }
  var CLASS_ORDER = {}; // { タブ: [区分key, …] }
  var YOMI_R = []; // 読み（ひらがな、読みの順）
  var YOMI_S = []; // 同じ位置の読みを持つ表記の配列

  function $(id) {
    return document.getElementById(id);
  }

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) {
      if (key === "text") node.textContent = attrs[key];
      else if (key === "html") node.innerHTML = attrs[key];
      else node.setAttribute(key, attrs[key]);
    });
    (children || []).forEach(function (child) {
      if (child) node.appendChild(child);
    });
    return node;
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  /* ---------- 検索 ---------- */

  // 全角英数・全角ハイフン等を半角に寄せ、大文字小文字を同一視する
  function norm(s) {
    return (s || "")
      .normalize("NFKC")
      .toLowerCase()
      .replace(/[‐‑‒–—―−]/g, "-");
  }

  /* 検索語がひらがな・カタカナだけのときは、読み表（data/yomi.json）で読みがその語で始まる表記にも一致させる。
   * inc は「どれかに一致すればよい語の組」の配列、terms は強調表示に使う語の一覧 */
  function parseQuery(q) {
    var inc = [];
    var exc = [];
    norm(q)
      .split(/\s+/)
      .filter(Boolean)
      .forEach(function (t) {
        if (t.length > 1 && t.charAt(0) === "-" && !/^-\d/.test(t)) {
          yomiGroups(t.slice(1)).forEach(function (g) {
            exc.push.apply(exc, g);
          });
        } else {
          inc.push.apply(inc, yomiGroups(t));
        }
      });
    var terms = [];
    inc.forEach(function (g) {
      terms.push.apply(terms, g);
    });
    return { inc: inc, exc: exc, terms: terms };
  }

  function toHiragana(s) {
    return s.replace(/[ァ-ヶ]/g, function (c) {
      return String.fromCharCode(c.charCodeAt(0) - 0x60);
    });
  }

  // 読みが r で始まる表記（ほかの表記を含む長い表記は、短い表記で一致するので除く）
  function yomiPrefix(r, exact) {
    var lo = 0;
    var hi = YOMI_R.length;
    while (lo < hi) {
      var mid = (lo + hi) >> 1;
      if (YOMI_R[mid] < r) lo = mid + 1;
      else hi = mid;
    }
    var found = [];
    for (var i = lo; i < YOMI_R.length && YOMI_R[i].indexOf(r) === 0; i++) {
      if (exact && YOMI_R[i] !== r) break;
      found.push.apply(found, YOMI_S[i]);
    }
    found.sort(function (x, y) {
      return x.length - y.length;
    });
    var kept = [];
    found.forEach(function (w) {
      if (kept.length >= 60) return;
      for (var k = 0; k < kept.length; k++) if (w.indexOf(kept[k]) !== -1) return;
      kept.push(norm(w));
    });
    return kept;
  }

  // 検索語 t を語の組の配列にする。読みに合う表記がなければ、読みを前後に分けてそれぞれの表記を探す
  function yomiGroups(t) {
    if (!YOMI_R.length || t.length < 2 || !/^[ぁ-ゖァ-ヺー]+$/.test(t)) return [[t]];
    var h = toHiragana(t);
    var hit = yomiPrefix(h, false);
    if (hit.length) return [[t].concat(hit)];
    for (var k = h.length - 1; k >= 2; k--) {
      if (h.length - k < 2) continue;
      var left = yomiPrefix(h.slice(0, k), true);
      if (!left.length) continue;
      var rest = yomiGroups(h.slice(k));
      if (rest.length === 1 && rest[0].length === 1) continue;
      return [left].concat(rest);
    }
    return [[t]];
  }

  // 本文の HTML から検索・抜粋用の文字列を作る
  function htmlText(html) {
    var box = document.createElement("div");
    box.innerHTML = html.replace(/<(br|\/p|\/h\d|\/tr|\/li|\/div)\b[^>]*>/gi, "$&\n");
    return box.textContent;
  }

  function hasTag(a, tab, cls, topic) {
    var t = a.tags[tab];
    if (!t) return false;
    if (cls && !t[cls]) return false;
    if (topic && t[cls] !== topic) return false;
    return true;
  }

  function searchArticles(list, q, filter) {
    var query = parseQuery(q);
    var out = [];
    list.forEach(function (a) {
      if (filter.type && a.type !== filter.type) return;
      if (filter.category && a.category !== filter.category) return;
      if (filter.cls && !hasTag(a, filter.tab, filter.cls, filter.topic)) return;
      var score = 0;
      for (var i = 0; i < query.exc.length; i++) if (a.norm.indexOf(query.exc[i]) !== -1) return;
      for (var j = 0; j < query.inc.length; j++) {
        // 組のうち一致する語のうち、いちばん高い点を採る
        var best = -1;
        query.inc[j].forEach(function (t) {
          if (a.norm.indexOf(t) === -1) return;
          var sc = 0;
          if (a.noNorm === t) sc += 1000;
          else if (a.noNorm && a.noNorm.indexOf(t) === 0) sc += 200;
          if (a.titleNorm.indexOf(t) !== -1) sc += 50;
          if (a.pathNorm.indexOf(t) !== -1) sc += 10;
          var p = -1;
          var c = 0;
          while ((p = a.bodyNorm.indexOf(t, p + 1)) !== -1 && c < 20) c++;
          if (sc + c > best) best = sc + c;
        });
        if (best < 0) return;
        score += best;
      }
      out.push({ a: a, score: score });
    });
    if (query.inc.length) {
      out.sort(function (x, y) {
        return y.score - x.score || x.a.order - y.a.order;
      });
    }
    return out.map(function (x) {
      return x.a;
    });
  }

  // 正規化前後の文字位置を対応付け、検索語に当たる範囲の [開始, 終了) を返す
  function markRanges(text, terms) {
    var map = [];
    var normed = "";
    for (var i = 0; i < text.length; i++) {
      var ch = norm(text.charAt(i));
      for (var k = 0; k < ch.length; k++) map.push(i);
      normed += ch;
    }
    var marks = new Array(text.length + 1).fill(0);
    terms.forEach(function (t) {
      if (!t) return;
      var p = -1;
      while ((p = normed.indexOf(t, p + 1)) !== -1) {
        marks[map[p]] += 1;
        marks[map[p + t.length - 1] + 1] -= 1;
      }
    });
    var ranges = [];
    var depth = 0;
    var start = -1;
    for (var j = 0; j <= text.length; j++) {
      depth += marks[j];
      if (depth > 0 && start < 0) start = j;
      if (depth <= 0 && start >= 0) {
        ranges.push([start, j]);
        start = -1;
      }
    }
    return ranges;
  }

  // 検索語を <mark> で強調した HTML を返す
  function highlight(text, terms) {
    if (!terms.length) return esc(text);
    var html = "";
    var last = 0;
    markRanges(text, terms).forEach(function (r) {
      html += esc(text.slice(last, r[0])) + "<mark>" + esc(text.slice(r[0], r[1])) + "</mark>";
      last = r[1];
    });
    return html + esc(text.slice(last));
  }

  // 描画済みの本文の文字に <mark> を付ける
  function highlightNode(root, terms) {
    if (!terms.length) return;
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    var nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(function (node) {
      var ranges = markRanges(node.nodeValue, terms);
      if (!ranges.length) return;
      var frag = document.createDocumentFragment();
      var s = node.nodeValue;
      var last = 0;
      ranges.forEach(function (r) {
        frag.appendChild(document.createTextNode(s.slice(last, r[0])));
        frag.appendChild(el("mark", { text: s.slice(r[0], r[1]) }));
        last = r[1];
      });
      frag.appendChild(document.createTextNode(s.slice(last)));
      node.parentNode.replaceChild(frag, node);
    });
  }

  // 検索語が本文にだけ一致したとき、一致箇所の前後を見出しの下に出す
  function snippet(a, terms) {
    var flat = a.bodyText.replace(/\s+/g, " ");
    var nf = norm(flat);
    var pos = -1;
    terms.forEach(function (t) {
      var p = nf.indexOf(t);
      if (p !== -1 && (pos === -1 || p < pos)) pos = p;
    });
    if (pos === -1) return "";
    var start = Math.max(0, pos - 40);
    return (start > 0 ? "…" : "") + flat.slice(start, start + 120) + (start + 120 < flat.length ? "…" : "");
  }

  /* ---------- 全文の表示 ---------- */

  var REF_SOURCES = [
    [/^(相基通|相続税法基本通達)$/, "kihon"],
    [/^(評基通|財産評価基本通達)$/, "hyoka"],
    [/^(措通|措置法通達)$/, "so"],
  ];
  var REF_RE = /(相基通|相続税法基本通達|評基通|財産評価基本通達|措通|措置法通達)\s*([0-9０-９][0-9０-９のー－\-・共]*[0-9０-９])/g;

  function normNum(s) {
    return norm(s).replace(/[ー－]/g, "-").replace(/\s+/g, "");
  }

  function renderBody(a, terms) {
    var box = el("div", { class: "article-body", html: a.html });
    Array.prototype.forEach.call(box.querySelectorAll("table"), function (t) {
      var w = el("div", { class: "article-table-wrap" });
      t.parentNode.replaceChild(w, t);
      w.appendChild(t);
    });
    // 収録済みのページへのリンクは、辞書の中の掲載先で開く
    Array.prototype.forEach.call(box.querySelectorAll("a[href]"), function (link) {
      var target = BY_URL[link.href] || BY_URL[link.href.split("#")[0]];
      if (target && target !== a) internalLink(link, target);
    });
    // 本文中の「相基通○-○」「評基通○」「措通○-○」を辞書の中の通達へのリンクにする
    var walker = document.createTreeWalker(box, NodeFilter.SHOW_TEXT);
    var nodes = [];
    while (walker.nextNode()) {
      var n = walker.currentNode;
      if (/相基通|相続税法基本通達|評基通|財産評価基本通達|措通|措置法通達/.test(n.nodeValue) && !n.parentNode.closest("a")) nodes.push(n);
    }
    nodes.forEach(function (node) {
      var s = node.nodeValue;
      var frag = document.createDocumentFragment();
      var last = 0;
      var changed = false;
      var m;
      REF_RE.lastIndex = 0;
      while ((m = REF_RE.exec(s))) {
        var kind = REF_SOURCES.filter(function (r) {
          return r[0].test(m[1]);
        })[0][1];
        var target = BY_NUM[kind + "|" + normNum(m[2])];
        if (!target || target === a) continue;
        frag.appendChild(document.createTextNode(s.slice(last, m.index)));
        var link = el("a", { href: target.url, text: m[0] });
        internalLink(link, target);
        frag.appendChild(link);
        last = m.index + m[0].length;
        changed = true;
      }
      if (!changed) return;
      frag.appendChild(document.createTextNode(s.slice(last)));
      node.parentNode.replaceChild(frag, node);
    });
    highlightNode(box, terms);
    return box;
  }

  function internalLink(link, target) {
    link.classList.add("xref");
    link.removeAttribute("target");
    link.title = TYPES[target.type].label + "「" + target.title + "」を開く";
    link.addEventListener("click", function (e) {
      e.preventDefault();
      openArticle(target);
    });
  }

  function noLabel(a) {
    if (a.type === "bk") return [a.date, a.dept].filter(Boolean).join("　");
    if (a.type === "kobetsu") return a.date;
    return a.number;
  }

  // 一覧の分類（目次の見出し）。通達は章・条、記事は国税庁の分類
  function categoryOf(type, cat) {
    if (TSUTATSU[type]) return cat[0] || "";
    return cat.join(" › ");
  }

  function renderOne(a, terms, opts) {
    var titleParts = [];
    var no = noLabel(a);
    var path = TSUTATSU[a.type] && a.type !== "kobetsu" ? a.path.slice(1).join(" › ") : opts.showType ? a.category : "";
    if (no || path) {
      titleParts.push(
        el("span", { class: "article-no" }, [
          no ? el("span", { html: highlight(no, terms) }) : null,
          path ? el("span", { class: "article-path", text: (no ? "　" : "") + path }) : null,
        ])
      );
    }
    titleParts.push(el("span", { class: "item-name", html: highlight(a.title, terms) }));
    var snip = terms.length && a.titleNorm.indexOf(terms[0]) === -1 ? snippet(a, terms) : "";
    if (snip) titleParts.push(el("span", { class: "article-snippet", html: highlight(snip, terms) }));

    var head = [];
    if (opts.showType) head.push(el("span", { class: "badge article-type badge-" + a.type, text: TYPES[a.type].short }));
    head.push(el("span", { class: "article-title" }, titleParts));
    var summary = el("summary", { class: "item-head article-head" }, head);

    var body = el("div", { class: "item-body" });
    var details = el("details", {}, [summary, body]);
    // 全文は開いたときに描画する
    details.addEventListener("toggle", function () {
      if (!details.open || body.childNodes.length) return;
      if (a.asof) body.appendChild(el("p", { class: "article-asof", text: asofLabel(a) }));
      body.appendChild(renderTags(a));
      body.appendChild(renderBody(a, terms));
      body.appendChild(
        el("p", {}, [el("a", { class: "article-link", href: a.url, target: "_blank", rel: "noopener", text: "国税庁の原文を開く ↗" })])
      );
    });
    return el("li", { class: "item article item-" + a.type }, [details]);
  }

  function asofLabel(a) {
    if (a.type === "kobetsu") return a.asof;
    if (/現在法令等$/.test(a.asof)) return a.asof.replace(/法令等$/, "の法令・通達等に基づく内容");
    return a.asof + "の法令・通達等に基づく内容";
  }

  // 項目が属する相続税・贈与税・財産評価の区分（押すとそのテーマを開く）
  function renderTags(a) {
    var box = el("div", { class: "article-tags" });
    DICT_TABS.forEach(function (tab) {
      var t = a.tags[tab];
      if (!t) return;
      CLASS_ORDER[tab].forEach(function (cls) {
        if (!t[cls]) return;
        var btn = el("button", { class: "chip", type: "button", text: TAB_LABEL[tab] + "：" + t[cls] });
        btn.addEventListener("click", function () {
          openTopic(tab, cls, t[cls]);
        });
        box.appendChild(btn);
      });
    });
    return box;
  }

  /*
   * 検索・絞り込み・一覧の 1 セットを作る。
   * prefix : 要素IDの接頭辞（例：kihon → #kihon-q, #kihon-results …）
   * opts.tab      : 相続税・贈与税・財産評価タブ。区分（data.bunrui）のボタンとテーマの一覧を出す
   * opts.types    : 辞書タブ。「すべて」の右に資料の種類のボタンを出す
   * opts.only     : この種別の記事だけを扱う
   * opts.showType : 各項目に種別バッジを出す
   * opts.allLabel : 分類の選択肢の「すべて」の表記
   */
  function setupDocTab(prefix, opts) {
    var st = { q: "", type: "", category: "", limit: PAGE_SIZE, focus: "" };
    var tab = opts.tab;
    var list = ARTICLES.filter(function (a) {
      if (opts.only) return a.type === opts.only;
      if (tab) return !!a.tags[tab];
      return true;
    });
    var chips = $(prefix + "-type-filters");
    var select = $(prefix + "-category-filter");
    var topicChips = $(prefix + "-topic-filters");
    var topicType = null;

    function setActive(box, code) {
      Array.prototype.forEach.call(box.children, function (b) {
        var active = b.getAttribute("data-type") === code;
        b.classList.toggle("is-active", active);
        b.setAttribute("aria-pressed", String(active));
      });
    }

    // 区分のテーマのタイトルをボタンで並べ、押すとそのテーマだけを表示する
    function syncTopicChips() {
      if (!topicChips) return;
      var cls = tab && BUNRUI[tab][st.type];
      topicChips.hidden = !cls;
      select.hidden = !!cls;
      if (!cls) {
        topicType = null;
        return;
      }
      if (topicType !== st.type) {
        topicType = st.type;
        topicChips.textContent = "";
        [{ key: "", name: "すべてのテーマ" }]
          .concat(
            cls.topics.map(function (t) {
              return { key: "topic|" + t.name, name: t.name };
            })
          )
          .forEach(function (t) {
            var btn = el("button", { class: "chip", type: "button", "data-type": t.key, "aria-pressed": "false", title: t.name, text: t.name });
            btn.addEventListener("click", function () {
              st.category = t.key;
              if (st.focus) clearFocus();
              renderList(true);
              if (btn.scrollIntoView) btn.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
            });
            topicChips.appendChild(btn);
          });
        topicChips.scrollLeft = 0;
      }
      setActive(topicChips, st.category);
    }

    function choose(code, topic) {
      st.type = code;
      setActive(chips, code);
      var b = chips.querySelector('.is-active[data-type="' + code + '"]');
      if (b && b.scrollIntoView) b.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
      fillCategories();
      if (topic) st.category = "topic|" + topic;
      renderList(true);
    }

    if ((tab || opts.types) && chips) {
      [""].concat(tab ? CLASS_ORDER[tab] : opts.types).forEach(function (code) {
        var btn = el("button", {
          class: "chip" + (!tab && code ? " chip-" + code : ""),
          type: "button",
          "data-type": code,
          "aria-pressed": "false",
          text: !code ? "すべて" : tab ? BUNRUI[tab][code].label : TYPES[code].label,
        });
        btn.addEventListener("click", function () {
          if (st.focus) clearFocus();
          choose(code);
        });
        chips.appendChild(btn);
      });
      setActive(chips, "");
    }

    select.addEventListener("change", function (e) {
      st.category = e.target.value;
      if (st.focus) clearFocus();
      renderList(true);
    });
    $(prefix + "-q").addEventListener("input", function (e) {
      st.q = e.target.value;
      if (st.focus) clearFocus();
      renderList(true);
    });

    // 区分の一覧や本文中のリンクから移動してきた項目だけを開いて表示する
    function clearFocus() {
      st.focus = "";
      if (view.id) {
        view.id = "";
        writeHash();
      }
    }
    INSTANCES[prefix] = {
      focus: function (id) {
        if (st.focus === id) return;
        st.focus = id;
        if (id) {
          st.q = "";
          $(prefix + "-q").value = "";
          st.category = "";
          select.value = "";
        }
        renderList(true);
      },
      topic: function (cls, topic) {
        st.q = "";
        $(prefix + "-q").value = "";
        st.focus = "";
        choose(cls, topic);
      },
    };

    // 分類の選択肢を作り直す（国税庁の目次順）
    function fillCategories() {
      var seen = {};
      select.textContent = "";
      var found = false;
      select.appendChild(el("option", { value: "", text: opts.allLabel || "すべての分類" }));
      list.forEach(function (a) {
        if (!tab && st.type && a.type !== st.type) return;
        var key = a.type + "|" + a.category;
        if (seen[key]) return;
        seen[key] = true;
        if (key === st.category) found = true;
        var label = opts.showType && !(!tab && st.type) ? TYPES[a.type].short + "：" + a.category : a.category;
        select.appendChild(el("option", { value: key, text: label }));
      });
      if (!found) st.category = "";
      select.value = st.category;
    }

    function renderList(resetLimit) {
      if (resetLimit) st.limit = PAGE_SIZE;
      // 分類の値は「種別|分類」（種別をまたいで同名の分類があるため）、テーマは「topic|テーマ」
      var cls = tab && BUNRUI[tab][st.type] ? st.type : "";
      syncTopicChips();
      if (st.focus) return renderFocus();
      var sep = st.category.indexOf("|");
      var isTopic = st.category.indexOf("topic|") === 0;
      var results = searchArticles(list, st.q, {
        type: cls ? "" : sep >= 0 && !isTopic ? st.category.slice(0, sep) : !tab ? st.type : "",
        category: !isTopic && sep >= 0 ? st.category.slice(sep + 1) : "",
        tab: tab,
        cls: cls,
        topic: isTopic ? st.category.slice(6) : "",
      });
      var terms = parseQuery(st.q).terms;
      var ul = $(prefix + "-results");
      ul.textContent = "";
      $(prefix + "-count").textContent =
        st.q.trim() || st.category || st.type ? results.length + " 件" : "全 " + results.length + " 件";
      if (cls) return renderTopics(ul, cls, results, terms);
      results.slice(0, st.limit).forEach(function (a) {
        ul.appendChild(renderOne(a, terms, opts));
      });
      if (!results.length) {
        ul.appendChild(el("li", { class: "empty" }, [el("p", { text: "該当する項目が見つかりませんでした。" })]));
      }
      if (results.length > st.limit) {
        var more = el("button", {
          class: "btn btn-ghost more",
          type: "button",
          text: "さらに表示（残り " + (results.length - st.limit) + " 件）",
        });
        more.addEventListener("click", function () {
          st.limit += PAGE_SIZE;
          renderList(false);
        });
        ul.appendChild(el("li", { class: "empty" }, [more]));
      }
      if (results.length === 1) ul.querySelector("details").open = true;
    }

    function renderFocus() {
      var ul = $(prefix + "-results");
      ul.textContent = "";
      var hit = list.filter(function (a) {
        return a.id === st.focus;
      });
      var fromLink = history.state && history.state.fromLink;
      var back = el("button", { class: "btn btn-ghost", type: "button", text: fromLink ? "← 前の画面に戻る" : "← 辞書へ" });
      back.addEventListener("click", function () {
        if (fromLink) history.back();
        else location.hash = "";
      });
      var all = el("button", { class: "btn btn-ghost", type: "button", text: "この一覧をすべて表示" });
      all.addEventListener("click", function () {
        clearFocus();
        renderList(true);
      });
      ul.appendChild(el("li", { class: "focus-bar" }, [back, all]));
      hit.forEach(function (a) {
        ul.appendChild(renderOne(a, [], opts));
      });
      if (hit.length) ul.querySelector("details").open = true;
      $(prefix + "-count").textContent = hit.length ? "選択した項目を表示しています" : "該当する項目が見つかりませんでした。";
    }

    // 区分：テーマごとにタイトル・説明文と、関係する通達・記事のタイトル（番号）の一覧を出す。
    // 項目を押すと、その項目が掲載されているタブに移動して全文を開く
    function renderTopics(ul, cls, results, terms) {
      var c = BUNRUI[tab][cls];
      ul.appendChild(
        el("li", { class: "class-intro" }, [
          el("h2", { class: "class-title", text: c.label }),
          el("p", { class: "class-desc", text: c.desc }),
          el("p", { class: "class-note", text: "説明は本辞書による概要です。項目を押すと、掲載先のタブで全文と国税庁の原文リンクを表示します。" }),
        ])
      );
      var topicFilter = st.category.indexOf("topic|") === 0 ? st.category.slice(6) : "";
      c.topics.forEach(function (t) {
        if (topicFilter && t.name !== topicFilter) return;
        var items = results.filter(function (a) {
          return a.tags[tab][cls] === t.name;
        });
        if (!items.length && st.q.trim()) return;
        var groups = [];
        Object.keys(TYPES).forEach(function (code) {
          var g = items.filter(function (a) {
            return a.type === code;
          });
          if (g.length) groups.push(renderRefGroup(code, g, terms));
        });
        ul.appendChild(
          el("li", { class: "topic-card" }, [
            el("h3", { class: "topic-title" }, [el("span", { text: t.name }), el("span", { class: "topic-count", text: items.length + " 件" })]),
            el("p", { class: "topic-desc", text: t.desc }),
            t.table ? renderRateTable(t.table) : null,
          ].concat((t.tables || []).map(renderRateTable), [
            t.note ? el("p", { class: "rate-note", text: t.note }) : null,
          ], groups))
        );
      });
      if (!results.length) {
        ul.appendChild(el("li", { class: "empty" }, [el("p", { text: "該当する項目が見つかりませんでした。" })]));
      }
    }

    // 速算表などの表（data.bunrui のテーマの table）
    function renderRateTable(tb) {
      var table = el("table", { class: "article-table rate-table" }, [
        el("thead", {}, [el("tr", {}, tb.head.map(function (h) {
          return el("th", h.length <= 8 ? { scope: "col", class: "nw", text: h } : { scope: "col", text: h });
        }))]),
        el("tbody", {}, tb.rows.map(function (row) {
          return el("tr", {}, row.map(function (c) {
            // 税率・控除額などの短い値は折り返さない
            return el("td", c.length <= 8 ? { class: "nw", text: c } : { text: c });
          }));
        })),
      ]);
      return el("div", { class: "rate-box" }, [
        tb.caption ? el("h4", { class: "rate-caption", text: tb.caption }) : null,
        el("div", { class: "article-table-wrap" }, [table]),
        tb.note ? el("p", { class: "rate-note", text: tb.note }) : null,
      ]);
    }

    function renderRefGroup(code, items, terms) {
      var box = el("div", { class: "ref-group" });
      box.appendChild(
        el("h4", { class: "ref-head" }, [
          el("span", { class: "badge badge-" + code, text: TYPES[code].label }),
          el("span", { class: "topic-count", text: items.length + " 件" }),
        ])
      );
      var listEl = el("ul", { class: "ref-list" });
      function fill(n) {
        listEl.textContent = "";
        items.slice(0, n).forEach(function (a) {
          var no = code === "bk" || code === "kobetsu" ? "" : noLabel(a);
          var btn = el("button", { class: "ref-link", type: "button" }, [
            no ? el("span", { class: "ref-no", html: highlight(no, terms) }) : null,
            el("span", { class: "ref-title", html: highlight(a.title, terms) }),
          ]);
          btn.addEventListener("click", function () {
            openArticle(a);
          });
          listEl.appendChild(el("li", {}, [btn]));
        });
      }
      fill(REF_PREVIEW);
      box.appendChild(listEl);
      if (items.length > REF_PREVIEW) {
        var more = el("button", { class: "ref-more", type: "button", text: "すべて表示（" + items.length + " 件）" });
        more.addEventListener("click", function () {
          fill(items.length);
          more.remove();
        });
        box.appendChild(more);
      }
      return box;
    }

    fillCategories();
    renderList(true);
  }

  /* ---------- タブ ---------- */

  var view = { tab: "dict", sub: { nta: "ta", tsu: "kihon" }, id: "" };

  function showView() {
    Array.prototype.forEach.call(document.querySelectorAll(".tab"), function (b) {
      var active = b.getAttribute("data-tab") === view.tab;
      b.classList.toggle("is-active", active);
      b.setAttribute("aria-selected", String(active));
    });
    TABS.forEach(function (t) {
      $("tab-" + t).hidden = t !== view.tab;
    });
    Object.keys(SUBS).forEach(function (t) {
      SUBS[t].forEach(function (s) {
        var active = s === view.sub[t];
        var b = document.querySelector('.subtab[data-sub="' + s + '"]');
        b.classList.toggle("is-active", active);
        b.setAttribute("aria-selected", String(active));
        $("sub-" + s).hidden = !active;
      });
    });
  }

  // タブは URL（#tab=tsu&sub=so、#tab=nta&sub=qa）でも開ける
  function readHash() {
    var p = new URLSearchParams(location.hash.slice(1));
    view.tab = TABS.indexOf(p.get("tab")) !== -1 ? p.get("tab") : "dict";
    Object.keys(SUBS).forEach(function (t) {
      view.sub[t] = view.tab === t && SUBS[t].indexOf(p.get("sub")) !== -1 ? p.get("sub") : SUBS[t][0];
    });
    view.id = p.get("id") || "";
  }

  // URL の id の項目を、掲載先の一覧で開く
  function applyFocus() {
    if (!ARTICLES.length) return;
    var target = view.id ? HOME[(ARTICLES_BY_ID[view.id] || {}).type] : null;
    Object.keys(HOME).forEach(function (code) {
      var h = HOME[code];
      var inst = INSTANCES[h.sub];
      if (!inst) return;
      var on = target && target.sub === h.sub && view.tab === h.tab && view.sub[h.tab] === h.sub;
      inst.focus(on ? view.id : "");
    });
  }

  function openArticle(a) {
    var h = HOME[a.type];
    view.tab = h.tab;
    view.sub[h.tab] = h.sub;
    view.id = a.id;
    var p = new URLSearchParams();
    p.set("tab", h.tab);
    if (h.sub !== SUBS[h.tab][0]) p.set("sub", h.sub);
    p.set("id", a.id);
    history.pushState({ fromLink: true }, "", "#" + p.toString());
    showView();
    applyFocus();
    window.scrollTo(0, 0);
  }

  // 相続税・贈与税・財産評価タブの区分のテーマを開く
  function openTopic(tab, cls, topic) {
    view.tab = tab;
    view.id = "";
    history.pushState({ fromLink: true }, "", "#tab=" + tab);
    showView();
    applyFocus();
    INSTANCES[tab].topic(cls, topic);
    window.scrollTo(0, 0);
  }

  function writeHash() {
    var p = new URLSearchParams();
    if (view.tab !== "dict") p.set("tab", view.tab);
    if (SUBS[view.tab] && view.sub[view.tab] !== SUBS[view.tab][0]) p.set("sub", view.sub[view.tab]);
    if (view.id) p.set("id", view.id);
    var h = p.toString();
    history.replaceState(history.state, "", h ? "#" + h : location.pathname + location.search);
  }

  function setupTabs() {
    Array.prototype.forEach.call(document.querySelectorAll(".tab"), function (b) {
      b.addEventListener("click", function () {
        view.tab = b.getAttribute("data-tab");
        view.id = "";
        writeHash();
        showView();
        applyFocus();
      });
    });
    Array.prototype.forEach.call(document.querySelectorAll(".subtab"), function (b) {
      b.addEventListener("click", function () {
        var s = b.getAttribute("data-sub");
        Object.keys(SUBS).forEach(function (t) {
          if (SUBS[t].indexOf(s) !== -1) view.sub[t] = s;
        });
        view.id = "";
        writeHash();
        showView();
        applyFocus();
      });
    });
    function onNavigate() {
      readHash();
      showView();
      applyFocus();
    }
    window.addEventListener("hashchange", onNavigate);
    window.addEventListener("popstate", onNavigate);
    readHash();
    showView();
  }

  /* ---------- 起動 ---------- */

  function init(data) {
    DICT_TABS.forEach(function (tab) {
      TAB_LABEL[tab] = data.bunrui[tab].label;
      BUNRUI[tab] = {};
      CLASS_ORDER[tab] = [];
      data.bunrui[tab].classes.forEach(function (c) {
        BUNRUI[tab][c.key] = c;
        CLASS_ORDER[tab].push(c.key);
      });
    });

    ARTICLES = data.items.map(function (r, i) {
      var bodyText = htmlText(r.html);
      var path = r.category || [];
      var extra = [r.date, r.dept].filter(Boolean).join(" ");
      return {
        id: r.id,
        type: r.kind,
        order: i,
        number: r.number || "",
        title: r.title,
        category: categoryOf(r.kind, path),
        path: path,
        html: r.html,
        asof: r.asof || "",
        date: r.date || "",
        dept: r.dept || "",
        url: r.url,
        tags: r.tags || {},
        bodyText: bodyText,
        noNorm: norm(r.number || ""),
        titleNorm: norm(r.title),
        pathNorm: norm(path.join(" ")),
        bodyNorm: norm(bodyText),
        norm: norm([r.number, extra, r.title, path.join(" ")].join(" ")) + "\n" + norm(bodyText),
      };
    });
    ARTICLES.forEach(function (a) {
      ARTICLES_BY_ID[a.id] = a;
      BY_URL[a.url] = a;
      var page = a.url.split("#")[0];
      if (!BY_URL[page]) BY_URL[page] = a;
      if (TSUTATSU[a.type] && a.number) BY_NUM[a.type + "|" + normNum(a.number)] = a;
    });

    var fetched = data.generated.slice(0, 10);
    Array.prototype.forEach.call(document.querySelectorAll(".fetched"), function (n) {
      n.textContent = fetched;
    });
    $("item-total").textContent = "収録 " + ARTICLES.length.toLocaleString() + " 件（取得日：" + fetched + "）";

    setupDocTab("dict", { types: Object.keys(TYPES), showType: true });
    setupDocTab("sozoku", { tab: "sozoku", showType: true });
    setupDocTab("zoyo", { tab: "zoyo", showType: true });
    setupDocTab("zaisan", { tab: "zaisan", showType: true });
    setupDocTab("kihon", { only: "kihon", allLabel: "すべての章" });
    setupDocTab("hyoka", { only: "hyoka", allLabel: "すべての章" });
    setupDocTab("so", { only: "so", allLabel: "すべての条" });
    setupDocTab("kobetsu", { only: "kobetsu" });
    setupDocTab("ta", { only: "ta" });
    setupDocTab("qa", { only: "qa" });
    setupDocTab("bk", { only: "bk" });
    applyFocus();
    getJSON("data/updates.json").then(renderUpdates, function () {
      // 更新記録がまだない（初回の取得から変更がない）ときは何も出さない
    });
  }

  // 辞書タブの「更新履歴」：月次更新で追加・削除・更新された項目（直近の記録から順に）
  function renderUpdates(history) {
    var box = $("dict-updates");
    if (!history || !history.length) return;
    var last = history[0];
    var count = function (h) {
      return "追加 " + h.added.length + " 件・更新 " + h.changed.length + " 件・削除 " + h.removed.length + " 件";
    };
    box.appendChild(el("summary", { class: "updates-head" }, [
      el("span", { class: "updates-title", text: "最近の更新（" + last.date + "）" }),
      el("span", { class: "updates-count", text: count(last) }),
    ]));
    history.slice(0, 6).forEach(function (h) {
      var sec = el("div", { class: "updates-entry" }, [el("h3", { class: "updates-date", text: h.date + "　" + count(h) })]);
      [["added", "追加"], ["changed", "更新"], ["removed", "削除"]].forEach(function (kv) {
        if (!h[kv[0]].length) return;
        var ul = el("ul", { class: "ref-list" });
        h[kv[0]].forEach(function (b) {
          var a = ARTICLES_BY_ID[b.id];
          var label = el("span", { class: "ref-title", text: b.title });
          var head = el("span", { class: "badge badge-" + b.kind, text: kv[1] + "：" + (TYPES[b.kind] ? TYPES[b.kind].short : b.kind) });
          if (a) {
            var btn = el("button", { class: "ref-link", type: "button" }, [head, label]);
            btn.addEventListener("click", function () {
              openArticle(a);
            });
            ul.appendChild(el("li", {}, [btn]));
          } else {
            // 削除された項目は辞書にないので、国税庁の元のページへのリンクにする
            ul.appendChild(el("li", {}, [el("a", { class: "ref-link", href: b.url, target: "_blank", rel: "noopener" }, [head, label])]));
          }
        });
        sec.appendChild(ul);
      });
      if (h.bunruiChanged) sec.appendChild(el("p", { class: "class-note", text: "区分・テーマの整理表も更新しました。" }));
      box.appendChild(sec);
    });
    box.hidden = false;
  }

  setupTabs();
  function getJSON(url) {
    return fetch(url).then(function (res) {
      if (!res.ok) throw new Error(res.status);
      return res.json();
    });
  }

  // 読み表がなくても、読み仮名による検索ができないだけで辞書は使える
  var yomiLoaded = getJSON("data/yomi.json")
    .then(function (rows) {
      rows.forEach(function (row) {
        YOMI_R.push(row[0]);
        YOMI_S.push(row[1].split("|"));
      });
    })
    .catch(function () {
      console.warn("data/yomi.json を読み込めませんでした（読み仮名による検索は使えません）");
    });

  Promise.all([getJSON("data/dictionary.json"), yomiLoaded])
    .then(function (res) {
      init(res[0]);
    })
    .catch(function (e) {
      console.error(e);
      $("dict-count").textContent =
        "data/dictionary.json を読み込めませんでした。scraper/build_dictionary.py でデータを生成し、HTTP サーバー経由で開いてください。";
    });
})();
