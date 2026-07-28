// ---- XSS 방벽: API 유래 문자열은 반드시 html`` 태그를 거쳐 DOM에 넣는다 ----
// html`` 은 모든 ${} 보간을 기본 이스케이프한다. 이미 html`` 로 만든 조각이나
// 신뢰된 정적 마크업만 raw() 로 감싸 그대로 삽입한다.
const esc = s => String(s).replace(/[&<>"']/g,
  c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const raw = s => ({__raw: s});
const html = (strs, ...vals) => strs.reduce((out, s, i) => {
  const v = vals[i - 1];
  return out + (v?.__raw ?? esc(v ?? "")) + s;
});

// ---- i18n: 활성 언어 카탈로그 조회(없으면 en 폴백, {name} 치환) ----
// tr 이라 이름 붙인 이유: 이 파일 곳곳의 콜백이 템플릿 객체를 `t` 로 받아 t() 와 충돌한다.
let LANG = "en";
let I18N = {en: {}, ko: {}};
function tr(key, fmt) {
  let s = (I18N[LANG] && I18N[LANG][key]) || (I18N.en && I18N.en[key]) || key;
  if (fmt) for (const k in fmt) s = s.replaceAll("{" + k + "}", fmt[k]);
  return s;
}
async function loadI18n() {
  try { I18N = await j("/assets/i18n.json"); } catch (e) { /* 기본값 유지 */ }
  try { LANG = (await j("/api/language")).language || "en"; } catch (e) { LANG = "en"; }
}

async function j(url, opts) { return (await fetch(url, opts)).json(); }

// 공용 모달 — 스킬/연결/템플릿 상세를 모두 중앙 팝업으로 띄운다(최하단 패널이
// 카드가 많아지면 화면 밖으로 밀리던 문제 해결). 내용 안의 요소는 고유 id 로 찾으므로
// 호출부의 기존 핸들러 배선은 그대로 둔다.
function openModal(bodyHtml) {
  const body = document.getElementById("modal-body");
  body.innerHTML = bodyHtml;
  document.getElementById("modal").hidden = false;
  return body;
}
function closeModal() { document.getElementById("modal").hidden = true; }

let TEMPLATES = [];

async function render() {
  const ints = await j("/api/integrations");
  document.getElementById("integration-list").innerHTML = ints.map(i =>
    html`<button class="chip ${i.connected ? "on" : "off"}" data-id="${i.id}" title="${i.detail ?? ""}">
      <span class="dot"></span>${i.name}<small>${i.connected ? tr("int.connected") : tr("int.disconnected")}</small></button>`
  ).join("");
  document.querySelectorAll("button.chip").forEach(b =>
    b.addEventListener("click", () => openIntegration(b.dataset.id)));

  const skills = await j("/api/skills");
  // 스킬·git·템플릿을 모두 한 그리드의 같은 카드로 — 에이전트/백그라운드 구분은
  // 카드 태그로만 가볍게 표시(예전엔 h3 하위 섹션으로 갈라 이중 헤딩이 무거웠다).
  const skillCard = s => {
    const blocked = s.status !== "available";
    const badge = blocked ? html`<em class="badge">${s.missing.join(", ")} ${tr("skill.connection_needed")}</em>` : "";
    const tag = s.surface === "service"
      ? html`<span class="card-tag" title="${tr("skill.background_title")}">${tr("skill.background")}</span>` : "";
    return html`<button class="skill ${s.status}" data-id="${s.id}" ${blocked ? "disabled" : ""}>
      <strong>${s.name}</strong><small>${(s.kinds || []).join(" · ")}</small>${raw(tag)}${raw(badge)}</button>`;
  };
  document.getElementById("skill-grid").innerHTML = skills.length
    ? html`<div class="skill-group">${raw(skills.map(skillCard).join(""))}</div>`
    : html`<div class="empty">${tr("skills.empty")}</div>`;

  document.querySelectorAll("button.skill:not([disabled])").forEach(b =>
    b.addEventListener("click", () => openSkill(b.dataset.id)));

  await renderTemplates();
}

async function renderTemplates() {
  TEMPLATES = await j("/api/templates");
  const host = document.getElementById("template-list");
  if (!host) return;
  if (!TEMPLATES.length) { host.innerHTML = `<div class="empty">${tr("tpl.empty")}</div>`; return; }
  // 스킬·git 과 동일한 박스(button.skill)를 재사용 — 카드 클릭 시 상세는 모달로.
  host.innerHTML = TEMPLATES.map(t => {
    const dbs = (t.databases || []).length, pgs = t.pages_count || 0;
    const summary = dbs ? tr("tpl.db_count", {n: dbs}) : (pgs ? tr("tpl.page_count", {n: pgs}) : tr("tpl.prompt_only"));
    return html`<button class="skill" data-slug="${t.slug}">
      <strong>${t.name}</strong><small>${summary}</small></button>`;
  }).join("");
  host.querySelectorAll("button.skill[data-slug]").forEach(b =>
    b.addEventListener("click", () => openTemplate(b.dataset.slug)));
}

function openNewTemplate() {
  const body = openModal(html`<h3>${tr("tpl.new_title")}</h3>
    <div class="tpl-mode">
      <label><input type="radio" name="tpl-mode" value="register" checked> ${tr("tpl.mode_register")}</label>
      <label><input type="radio" name="tpl-mode" value="blueprint"> ${tr("tpl.mode_blueprint")}</label>
    </div>
    <div id="mode-register">
      <p class="detail">${tr("tpl.register_desc")}</p>
      <div class="tpl-field">
        <label class="field-label" for="reg-url">Notion URL</label>
        <input id="reg-url" placeholder="https://www.notion.so/…">
      </div>
      <div class="modal-actions"><button id="reg-go" class="btn-primary">${tr("tpl.register_btn")}</button></div>
      <p id="reg-error" class="detail reg-error"></p>
    </div>
    <div id="mode-blueprint" hidden>
      <p class="detail">${tr("tpl.blueprint_desc")}</p>
      <div class="tpl-field">
        <label class="field-label" for="np-name">${tr("tpl.name_label")}</label>
        <input id="np-name" placeholder="${tr("tpl.name_placeholder")}">
      </div>
      <div class="tpl-field">
        <label class="field-label" for="np-prompt">${tr("tpl.prompt_label_new")}</label>
        <textarea id="np-prompt" class="tpl-prompt" rows="12" placeholder="${tr("tpl.prompt_placeholder_new")}"></textarea>
      </div>
      <div class="modal-actions"><button id="np-save" class="btn-primary">${tr("tpl.create_btn")}</button></div>
      <p id="np-out" class="detail"></p>
    </div>`);
  const reg = body.querySelector("#mode-register");
  const bp = body.querySelector("#mode-blueprint");
  body.querySelectorAll("input[name=tpl-mode]").forEach(r =>
    r.addEventListener("change", () => {
      const isReg = body.querySelector("input[name=tpl-mode]:checked").value === "register";
      reg.hidden = !isReg; bp.hidden = isReg;
    }));

  const regBtn = body.querySelector("#reg-go");
  regBtn.addEventListener("click", async () => {
    const url = body.querySelector("#reg-url").value.trim();
    const err = body.querySelector("#reg-error");
    err.textContent = "";
    if (!url) { err.textContent = tr("tpl.url_required"); return; }
    regBtn.disabled = true; regBtn.textContent = tr("tpl.registering");
    const res = await j("/api/templates/register", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({url})});
    if (res.error) {
      err.textContent = res.error;              // 실패·모호 → 인라인(모달 유지)
      regBtn.disabled = false; regBtn.textContent = tr("tpl.register_btn");
      return;
    }
    await render();
    openTemplate(res.slug);                     // 등록된 인스턴스 모달로
  });

  body.querySelector("#np-save").addEventListener("click", async () => {
    const name = body.querySelector("#np-name").value.trim();
    const prompt = body.querySelector("#np-prompt").value;
    if (!name) { body.querySelector("#np-out").textContent = tr("tpl.name_required"); return; }
    const res = await j("/api/templates", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({name, prompt})});
    if (res.error) { body.querySelector("#np-out").textContent = tr("common.failed_prefix") + res.error; return; }
    await render();
    openTemplate(res.slug);          // 만든 뒤 그 템플릿 모달로
  });
}

function structHtml(t) {
  if (!t.page_id) return html`<p class="detail">${tr("tpl.promptonly_struct")}</p>`;
  const dbs = (t.databases || []).map(d => d.title || d.key);
  const items = [];
  if (dbs.length) items.push(tr("tpl.databases_prefix", {list: dbs.join(", ")}));
  if (t.pages_count) items.push(tr("tpl.page_count", {n: t.pages_count}));
  return items.length
    ? html`<ul class="tpl-struct">${raw(items.map(s => html`<li>${s}</li>`).join(""))}</ul>`
    : html`<p class="detail">${tr("tpl.no_structure")}</p>`;
}

function openTemplate(slug) {
  const t = TEMPLATES.find(x => x.slug === slug);
  if (!t) return;
  const syncBtn = t.page_id
    ? html`<button type="button" id="tpl-refresh" class="btn-quiet">${tr("tpl.sync")}</button>` : "";
  const body = openModal(html`<h3>${t.name} <small class="modal-sub">${t.slug}</small></h3>
    <div class="tpl-field">
      <span class="field-label">${tr("tpl.structure_label")} <small class="modal-sub">${tr("tpl.readonly")}</small></span>
      <div id="tpl-struct-box">${raw(structHtml(t))}</div>
    </div>
    <div class="tpl-field">
      <label class="field-label" for="tpl-prompt">${tr("tpl.prompt_label_edit")}</label>
      <textarea id="tpl-prompt" class="tpl-prompt" rows="12"
        placeholder="${tr("tpl.prompt_placeholder_edit")}"></textarea>
    </div>
    <div class="modal-actions">
      <button id="tpl-save" class="btn-primary">${tr("common.save")}</button>${raw(syncBtn)}
      <button type="button" id="tpl-remove" class="btn-quiet tpl-remove"
        title="${tr("tpl.unregister_title")}">${tr("tpl.unregister")}</button>
    </div>`);
  // 사용자 데이터는 .value 로 넣는다(HTML 주입/이스케이프 경계 밖에서 안전하게)
  body.querySelector("#tpl-prompt").value = t.prompt || "";
  body.querySelector("#tpl-save").addEventListener("click", async () => {
    const prompt = body.querySelector("#tpl-prompt").value;
    const res = await j(`/api/templates/${slug}/prompt`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({prompt})});
    const btn = body.querySelector("#tpl-save");
    btn.textContent = res.error ? tr("tpl.save_failed") : tr("tpl.saved");
    const i = TEMPLATES.findIndex(x => x.slug === slug);
    if (i >= 0 && !res.error) TEMPLATES[i].prompt = res.prompt;
    setTimeout(() => { btn.textContent = tr("common.save"); }, 1500);
  });
  // 구조 갱신 — Notion 스키마 재조회. #tpl-struct-box 만 교체해 편집 중인 프롬프트는 보존.
  // page-less 템플릿은 syncBtn 이 없어 rb 가 null — 배선을 건너뛴다.
  const rb = body.querySelector("#tpl-refresh");
  if (rb) rb.addEventListener("click", async () => {
    rb.disabled = true; rb.textContent = tr("tpl.syncing");
    const res = await j(`/api/templates/${slug}/refresh`, {method: "POST"});
    if (res.error) {
      rb.textContent = tr("tpl.sync_failed");
    } else {
      const i = TEMPLATES.findIndex(x => x.slug === slug);
      if (i >= 0) { TEMPLATES[i].databases = res.databases; TEMPLATES[i].pages_count = res.pages_count; }
      body.querySelector("#tpl-struct-box").innerHTML = structHtml(res);
      rb.textContent = tr("tpl.synced");
    }
    setTimeout(() => { rb.textContent = tr("tpl.sync"); rb.disabled = false; }, 1500);
  });
  // 등록 해제 — 로컬 프로필만 지운다(Notion 은 보존). 확인 후 DELETE → 목록 갱신·모달 닫기.
  body.querySelector("#tpl-remove").addEventListener("click", async () => {
    if (!confirm(tr("tpl.unregister_confirm", {name: t.name}))) return;
    const res = await j(`/api/templates/${slug}`, {method: "DELETE"});
    if (res && res.error) { alert(tr("tpl.unregister_failed_prefix") + res.error); return; }
    const i = TEMPLATES.findIndex(x => x.slug === slug);
    if (i >= 0) TEMPLATES.splice(i, 1);
    closeModal();
    await renderTemplates();
  });
}

async function openSkill(id) {
  // 템플릿 카드 = "템플릿 추가"(기존 URL 등록 | 프롬프트 청사진). 별도 '+ 템플릿' 버튼을
  // 없애고 카드 클릭으로 통합 — settings 는 등록·프롬프트 작성이 전부(agent 사용 노트
  // 생성은 여기 몫이 아님). 실행 패널(agent 노트 등록)은 web 에서 거치지 않는다.
  if (id === "templates") return openNewTemplate();
  const cards = await j("/api/skills");
  const card0 = cards.find(c => c.id === id) || {};
  if (card0.runnable) return openRunPanel(id, card0);   // 실행형(library)은 실행 패널로
  const schema = await j(`/api/skills/${id}/options`);
  const saved = await j(`/api/skills/${id}/config`);
  const settings = Object.entries(schema).filter(([, v]) => !v.runtime);
  const fields = settings.map(([k, v]) => {
    const cur = saved[k];
    const label = v.label || k;
    const help = v.help ? html`<small class="hint">${v.help}</small>` : "";
    let control;
    if (v.type === "bool") {
      const checked = (cur ?? v.default) ? "checked" : "";
      control = html`<label class="switch"><input type="checkbox" name="${k}" ${checked}><span class="slider"></span></label>`;
    } else if (v.type === "select") {
      const opts = (v.choices || []).map(c =>
        html`<option ${((cur ?? v.default) === c) ? "selected" : ""}>${c}</option>`).join("");
      control = html`<select name="${k}">${raw(opts)}</select>`;
    } else if (v.type === "number") {
      control = html`<input type="number" name="${k}" value="${cur ?? ""}" placeholder="${v.default ?? ""}">`;
    } else {
      control = html`<input name="${k}" value="${cur ?? ""}" placeholder="${v.default ?? ""}">`;
    }
    return html`<div class="field">
      <div class="field-text"><span class="field-label">${label}</span>${raw(help)}</div>
      <div class="field-ctl">${raw(control)}</div></div>`;
  }).join("");
  // 카드가 선언한 사용법/설정 절차 — verb 스킬은 `run`으로 실행되지 않으므로
  // 일괄 안내를 쓰면 동작하지 않는 명령을 알려주게 된다 (card0 은 위에서 이미 조회)
  const usageRow = card0.usage
    ? html`<p class="detail">${tr("skill.usage_prefix")} <code>${card0.usage}</code>. ${tr("skill.saves_defaults")}</p>`
    : html`<p class="detail">${tr("skill.usage_none")}</p>`;
  // 외부 앱 설정처럼 API로 자동화할 수 없는 단계 — 설치자가 여기서 그대로 따라할 수 있게
  const steps = (card0.setup_steps || []).map(s => html`<li>${s}</li>`).join("");
  const setupRow = steps ? html`
    <div class="field field-col">
      <span class="field-label">${tr("skill.setup_manual")}</span>
      <div class="install-hint"><ol>${raw(steps)}</ol></div>
    </div>` : "";
  openModal(html`<h3>${id} settings</h3>
    ${raw(usageRow)}${raw(setupRow)}
    <form id="opts">${raw(fields)}
    <button type="submit" class="btn-primary">${tr("common.save")}</button></form>
    <p id="out" class="detail"></p>`);
  document.getElementById("opts").addEventListener("submit", async e => {
    e.preventDefault();
    const form = e.target;
    const body = {};
    settings.forEach(([k, v]) => {
      const el = form.elements[k];
      if (!el) return;
      body[k] = v.type === "bool" ? (el.checked ? "true" : "") : el.value;
    });
    const res = await j(`/api/skills/${id}/config`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body)});
    document.getElementById("out").textContent =
      res.error ? (tr("common.save_failed_prefix") + res.error) : tr("common.saved");
  });
}

// 실행형 스킬 패널 — 옵션을 '저장 설정'이 아니라 '실행 파라미터'로 다루고, 실행 버튼이
// run 엔드포인트를 호출한 뒤 상태를 폴링해 진행/결과를 보여준다(설정 Save 아님).
async function openRunPanel(id, card) {
  const schema = await j(`/api/skills/${id}/options`);
  const fields = Object.entries(schema).map(([k, v]) => {
    const label = v.label || k;
    const help = v.help ? html`<small class="hint">${v.help}</small>` : "";
    // 실행 파라미터의 bool 은 '저장 설정' 같은 토글스위치가 아니라 '이번 실행 옵션'
    // 으로 읽히게 평범한 체크박스로 렌더한다(설정 폼의 .switch 와 구분).
    const control = v.type === "bool"
      ? html`<input type="checkbox" name="${k}" class="run-check" ${v.default ? "checked" : ""}>`
      : html`<input name="${k}" placeholder="${v.default ?? ""}">`;
    return html`<div class="field">
      <div class="field-text"><span class="field-label">${label}</span>${raw(help)}</div>
      <div class="field-ctl">${raw(control)}</div></div>`;
  }).join("");
  const body = openModal(html`<h3>${card.name}</h3>
    <p class="detail">${tr("run.is_runnable")}</p>
    <form id="run-form">${raw(fields)}
      <button type="submit" class="btn-primary">${card.run_label || tr("run.run_btn")}</button></form>
    <p id="run-out" class="detail"></p>`);
  body.querySelector("#run-form").addEventListener("submit", async e => {
    e.preventDefault();
    const form = e.target;
    const opts = {};
    Object.entries(schema).forEach(([k, v]) => {
      const el = form.elements[k];
      if (el) opts[k] = v.type === "bool" ? el.checked : el.value;
    });
    const btn = form.querySelector("button");
    const out = body.querySelector("#run-out");
    btn.disabled = true;
    out.textContent = tr("run.running");
    const start = await j(`/api/skills/${id}/run`, {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(opts)});
    if (!start.job_id) {
      out.textContent = tr("run.start_failed_prefix") + (start.error || tr("run.unknown"));
      btn.disabled = false;
      return;
    }
    const poll = setInterval(async () => {
      const st = await j(`/api/skills/${id}/status/${start.job_id}`);
      out.textContent = st.done
        ? (st.message || (st.ok ? tr("run.done") : tr("run.failed")))
        : ((st.logs || []).slice(-1)[0] || tr("run.running"));
      if (st.done) {
        clearInterval(poll);
        btn.disabled = false;
        if (st.ok) render();          // 등록 성공 시 템플릿 목록·카드 상태 갱신
      }
    }, 800);
  });
}

async function openIntegration(id) {
  const ints = await j("/api/integrations");
  const info = ints.find(x => x.id === id) || {name: id, connected: false, detail: ""};

  // 미연결 안내 블록 — 카탈로그의 신뢰된 정적 마크업만(서버 문자열 미삽입) → raw() 로 삽입해도 안전
  const GUIDES = {
    notion: {label: tr("guide.notion.label"), html: tr("guide.notion.html")},
    git: {label: tr("guide.git.label"), html: tr("guide.git.html")},
    agent: {label: tr("guide.agent.label"), html: tr("guide.agent.html")},
  };

  // 헤더 우측 액션 + 제목 아래 상태 한 줄 (라벨 없음)
  const disconnect = info.connected && id === "notion"
    ? html`<button type="button" class="btn-quiet" id="int-disconnect">${tr("int.disconnect")}</button>` : "";
  const head = html`
    <div class="int-head"><h3>${info.name}</h3>
      <div class="int-actions">
        <button type="button" class="btn-quiet" id="int-test">${tr("int.test")}</button>${raw(disconnect)}
      </div>
    </div>
    <div class="int-status ${info.connected ? "on" : "off"}">
      <span class="status-dot"></span><span id="int-detail">${info.detail ?? ""}</span>
    </div>`;
  const g = GUIDES[id];
  const guideRow = !info.connected && g ? html`
    <div class="field field-col">
      <span class="field-label">${g.label}</span>
      <div class="install-hint">${raw(g.html)}</div>
    </div>` : "";

  let body;
  if (id === "notion" && !info.connected) {
    body = html`<form id="int-connect">${raw(guideRow)}
      <div class="field">
        <div class="field-text"><span class="field-label">${tr("int.notion_token_label")}</span>
          <small class="hint">${raw(tr("int.notion_token_hint"))}</small></div>
        <div class="field-ctl"><input type="password" name="token" placeholder="ntn_..." class="wide"></div>
      </div>
      <button type="submit" class="btn-primary">${tr("int.connect")}</button>
    </form>`;
  } else {
    body = guideRow;
  }
  openModal(head + body);

  // 액션 후에는 패널을 새 상태로 다시 그리고, 결과 메시지를 상태줄에 표시
  const show = async r => {
    await render();
    await openIntegration(id);
    const el = document.getElementById("int-detail");
    if (el) el.textContent = r.detail || r.error || "";
  };
  document.getElementById("int-test").addEventListener("click", async e => {
    // 결과가 기존 상태와 같아도 검사가 돌았음을 보이게 — 확인 중 표시 + 이중 클릭 방지
    e.target.disabled = true;
    const detailEl = document.getElementById("int-detail");
    if (detailEl) detailEl.textContent = tr("int.checking");
    const r = await j(`/api/integrations/${id}/test`, {method: "POST"});
    await show({detail: (r.detail || r.error || "") + " — " + tr("int.just_checked")});
  });
  const form = document.getElementById("int-connect");
  if (form && id === "notion") {
    form.addEventListener("submit", async e => {
      e.preventDefault();
      const token = new FormData(e.target).get("token");
      show(await j(`/api/integrations/notion/connect`, {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({token})}));
    });
  }
  const disconnectBtn = document.getElementById("int-disconnect");
  if (disconnectBtn) {
    disconnectBtn.addEventListener("click", async () =>
      show(await j(`/api/integrations/${id}/disconnect`, {method: "POST"})));
  }
}

// 로드 시 정적 DOM(index.html)의 data-i18n 텍스트/aria 를 활성 언어로 주입 + 선택기 반영
function applyStaticI18n() {
  document.documentElement.lang = LANG;
  document.querySelectorAll("[data-i18n]").forEach(el => { el.textContent = tr(el.dataset.i18n); });
  document.querySelectorAll("[data-i18n-aria]").forEach(el =>
    el.setAttribute("aria-label", tr(el.dataset.i18nAria)));
  const sel = document.getElementById("lang-select");
  if (sel) sel.value = LANG;
}

// node 테스트가 파일을 평가해 esc/html 헬퍼만 검사할 수 있도록 브라우저에서만 초기 렌더
if (typeof document !== "undefined") {
  (async () => {
    await loadI18n();                 // 활성 언어 + 카탈로그를 렌더 전에 확정
    applyStaticI18n();
    const sel = document.getElementById("lang-select");
    if (sel) sel.addEventListener("change", async () => {
      await j("/api/language", {method: "POST", headers: {"Content-Type": "application/json"},
                                body: JSON.stringify({language: sel.value})});
      location.reload();              // 가장 단순: 재로드로 새 언어 부트스트랩
    });
    await render();
    // 모달 닫기: 백드롭 클릭 · X · Esc
    document.querySelector("#modal .modal-backdrop").addEventListener("click", closeModal);
    document.querySelector("#modal .modal-close").addEventListener("click", closeModal);
    document.addEventListener("keydown", e => { if (e.key === "Escape") closeModal(); });
  })();
}
