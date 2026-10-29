"""签署人 H5 面（微信内浏览器，lex-contract-esignature 任务 5.x 的产品脸）。

GET /api/esignature/p/{link_token}：

- 任务状态异常（撤销/失效/不存在）→ 服务端直接渲染如实状态页（410/404/409 +
  中文提示），无需 JS 也讲得清「为什么不能签」。
- 正常 → 渲染签署应用页：无构建链的纯内联 HTML/JS，按 open→preview→realname→
  sign 走既有 JSON 接口（行为真源仍是 service，本文件只管展示）。

令牌注入用 replace 而非 format/f-string（内联 JS 大括号密集，f-string 嵌
`${}` 是已知翻车点）。链接 token 仅在 resolve_signer 通过后到达此处。
"""

from __future__ import annotations

from markupsafe import escape

_STATUS_TMPL = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>电子签署</title>
<style>
body{font-family:-apple-system,PingFang SC,Microsoft YaHei,sans-serif;background:#f6f7f9;
color:#1b2a42;display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0}
.card{background:#fff;border:1px solid #d9dfe8;border-radius:8px;padding:32px 28px;max-width:420px;
text-align:center}
.card h2{margin:0 0 12px;font-size:1.15rem;color:#12305b}
.card p{margin:0;line-height:1.8;font-size:.95rem}
</style></head><body><div class="card"><h2>无法打开签署</h2><p>__MESSAGE__</p></div></body></html>
"""

_PAGE_TMPL = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>电子签署</title>
<style>
body{font-family:-apple-system,PingFang SC,Microsoft YaHei,sans-serif;background:#f6f7f9;
color:#1b2a42;margin:0;padding:16px}
.wrap{max-width:640px;margin:0 auto}
h1{font-size:1.2rem;color:#12305b;margin:8px 0 2px}
#who{font-size:.9rem;color:#4e5f7b;margin-bottom:16px}
.step{background:#fff;border:1px solid #d9dfe8;border-radius:8px;padding:16px;margin-bottom:12px}
.step h3{margin:0 0 10px;font-size:1rem}
button{background:#12305b;color:#fff;border:0;border-radius:6px;padding:10px 18px;
font-size:.95rem;cursor:pointer}
button:disabled{opacity:.5;cursor:default}
input,select{width:100%;box-sizing:border-box;padding:10px;margin:6px 0;
border:1px solid #b6c1d1;border-radius:6px;font-size:.95rem}
iframe{width:100%;height:320px;border:1px solid #d9dfe8;border-radius:6px;margin-top:10px;
background:#fff}
#err{color:#a6402f;font-size:.9rem;margin:8px 0;min-height:1.2em}
#result{background:#f4e5e1;color:#a6402f;border:1px solid #b6c1d1;border-radius:8px;
padding:16px;margin-bottom:12px;display:none;font-size:1rem}
.note{font-size:.8rem;color:#4e5f7b;margin-top:18px;text-align:center}
</style></head><body><div class="wrap">
<h1 id="task-title">加载中…</h1><div id="who"></div>
<div id="result"></div><div id="err"></div>
<div class="step" id="step1"><h3>第一步 · 阅读合同全文</h3>
<button id="btn-preview" disabled>打开合同预览</button>
<iframe id="doc" title="合同全文" style="display:none"></iframe></div>
<div class="step" id="step2"><h3>第二步 · 实名认证</h3>
<input id="name" placeholder="真实姓名" autocomplete="off">
<input id="idno" placeholder="身份证号 / 统一社会信用代码" autocomplete="off">
<button id="btn-verify" disabled>实名核验</button></div>
<div class="step" id="step3" style="display:none"><h3>第三步 · 意愿确认与签署</h3>
<select id="intent">
<option value="h5-confirm">已阅读并确认签署意愿</option>
<option value="face">人脸核身确认</option>
<option value="sms">短信验证码确认</option>
</select>
<button id="btn-sign">确认签署</button></div>
<div class="note">实名认证与签署意愿由持牌电子签名服务商通道完成</div>
</div>
<script>
var TOKEN = "__TOKEN__";
var API = "/api/esignature/s/" + TOKEN;
var sess = "";
function $(id){ return document.getElementById(id); }
function fail(e){ $("err").textContent = (e && e.message) ? e.message : String(e); }
function call(url, opt){
  return fetch(url, opt).then(function(r){
    return r.json().then(function(j){
      if (!r.ok){
        var d = j && j.detail ? j.detail : ("请求失败(" + r.status + ")");
        throw new Error(typeof d === "string" ? d : JSON.stringify(d));
      }
      return j;
    });
  });
}
function boot(){
  call(API).then(function(j){
    if (j.already_signed){
      $("result").style.display = "block";
      $("result").textContent = "该签署链接已完成签署，无需重复操作。";
      $("step1").style.display = "none"; $("step2").style.display = "none";
      return;
    }
    sess = j.session_token;
    $("task-title").textContent = j.task_title;
    $("who").textContent = "签署人：" + j.signer.name + "（第" + j.signer.seq + "顺位）";
    $("name").value = j.signer.name;
    $("btn-preview").disabled = false;
    $("btn-verify").disabled = false;
  }).catch(fail);
}
function preview(){
  $("err").textContent = "";
  fetch(API + "/preview", { headers: { "x-esign-session": sess } }).then(function(r){
    if (!r.ok) throw new Error("合同预览获取失败");
    return r.blob();
  }).then(function(b){
    $("doc").src = URL.createObjectURL(b);
    $("doc").style.display = "block";
  }).catch(fail);
}
function verify(){
  $("err").textContent = "";
  call(API + "/realname", {
    method: "POST",
    headers: { "content-type": "application/json", "x-esign-session": sess },
    body: JSON.stringify({ name: $("name").value, credential: { method: "three-element", serial: $("idno").value } })
  }).then(function(){
    $("btn-verify").disabled = true;
    $("step3").style.display = "block";
  }).catch(fail);
}
function sign(){
  $("err").textContent = "";
  call(API + "/sign", {
    method: "POST",
    headers: { "content-type": "application/json", "x-esign-session": sess },
    body: JSON.stringify({ intent_method: $("intent").value })
  }).then(function(j){
    $("step1").style.display = "none"; $("step2").style.display = "none"; $("step3").style.display = "none";
    $("result").style.display = "block";
    $("result").textContent = j.task_status === "completed"
      ? "签署完成。合同与签署记录已存证，发起方可下载出证包。"
      : "您已完成签署，等待其余签署人完成。";
  }).catch(fail);
}
window.onload = function(){
  boot();
  $("btn-preview").onclick = preview;
  $("btn-verify").onclick = verify;
  $("btn-sign").onclick = sign;
};
</script></body></html>
"""


def render_page(link_token: str) -> str:
    return _PAGE_TMPL.replace("__TOKEN__", str(escape(link_token)))


def render_status(detail: str) -> str:
    return _STATUS_TMPL.replace("__MESSAGE__", str(escape(detail)))


__all__ = ["render_page", "render_status"]
