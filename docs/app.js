// AI 檢測的對話畫面。後端網址在 config.js，這裡沒有金鑰。
const userText = document.querySelector("#userText");
const userImage = document.querySelector("#userImage");
const chatForm = document.querySelector("#chatForm");
const chatLog = document.querySelector("#chatLog");
const chatEmpty = document.querySelector("#chatEmpty");
const sendBtn = document.querySelector("#checkBtn");
const clearBtn = document.querySelector("#clearBtn");
const fileName = document.querySelector("#chatFileName");

function apiUrl(path) {
  const base = (window.API_BASE_URL || "").replace(/\/$/, "");
  return base + path;
}

function addMessage(role, text) {
  if (chatEmpty) chatEmpty.hidden = true;
  const item = document.createElement("article");
  item.className = "chat-msg " + role;
  const bubble = document.createElement("div");
  bubble.className = "chat-bubble";
  bubble.textContent = text;
  item.appendChild(bubble);
  chatLog.appendChild(item);
  chatLog.scrollTop = chatLog.scrollHeight;
  return bubble;
}

function resizeText() {
  userText.style.height = "auto";
  userText.style.height = Math.min(userText.scrollHeight, 160) + "px";
}

function showFileName() {
  const file = userImage.files[0];
  if (!fileName) return;
  if (!file) {
    fileName.hidden = true;
    fileName.textContent = "";
    return;
  }
  fileName.hidden = false;
  fileName.textContent = "已附上圖片：" + file.name;
}

async function readResult(response) {
  const data = await response.json();
  if (!data || !data.result) return "沒有回傳結果。";
  return data.result;
}

async function ask() {
  const text = userText.value.trim();
  const file = userImage.files[0];
  if (!text && !file) return;

  let shown = text;
  if (file) {
    shown = text ? text + "\n（圖片：" + file.name + "）" : "（圖片：" + file.name + "）";
  }
  addMessage("user", shown);
  userText.value = "";
  resizeText();
  sendBtn.disabled = true;
  const pending = addMessage("assistant", "分析中，請稍候…");

  try {
    if (text) {
      const response = await fetch(apiUrl("/api/check"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: text })
      });
      pending.textContent = await readResult(response);
    }
    if (file) {
      const imageBubble = text ? addMessage("assistant", "圖片分析中…") : pending;
      const formData = new FormData();
      formData.append("image", file);
      const response = await fetch(apiUrl("/api/check-image"), {
        method: "POST",
        body: formData
      });
      imageBubble.textContent = await readResult(response);
    }
  } catch (error) {
    pending.textContent = "無法連線到伺服器。服務如果剛睡醒，請再等一下重試。";
  }

  userImage.value = "";
  showFileName();
  sendBtn.disabled = false;
  userText.focus();
}

if (chatForm) {
  chatForm.addEventListener("submit", function (event) {
    event.preventDefault();
    ask();
  });

  // 中文輸入時，第一次 Enter 只是選字、消掉底線。第二次 Enter 才送出。
  let composing = false;
  let skipEnter = false;
  userText.addEventListener("compositionstart", function () {
    composing = true;
  });
  userText.addEventListener("compositionend", function () {
    composing = false;
    skipEnter = true;
    setTimeout(function () {
      skipEnter = false;
    }, 0);
  });
  userText.addEventListener("keydown", function (event) {
    if (event.key !== "Enter" || event.shiftKey) return;
    if (composing || event.isComposing || event.keyCode === 229 || skipEnter) return;
    event.preventDefault();
    ask();
  });
  userText.addEventListener("input", resizeText);
  userImage.addEventListener("change", showFileName);

  clearBtn.addEventListener("click", function () {
    chatLog.querySelectorAll(".chat-msg").forEach(function (item) {
      item.remove();
    });
    if (chatEmpty) chatEmpty.hidden = false;
    userText.value = "";
    userImage.value = "";
    showFileName();
    resizeText();
    userText.focus();
  });
}
