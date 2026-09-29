// 先用 querySelector 找到頁面上的元素
const userText = document.querySelector("#userText");
const userImage = document.querySelector("#userImage");
const checkBtn = document.querySelector("#checkBtn");
const checkImageBtn = document.querySelector("#checkImageBtn");
const clearBtn = document.querySelector("#clearBtn");
const resultBox = document.querySelector("#resultBox");

// API_BASE_URL 來自 config.js
// 本機留空；GitHub Pages 請填 Render 後端網址
function apiUrl(path) {
  const base = (window.API_BASE_URL || "").replace(/\/$/, "");
  return base + path;
}

function setLoading(isLoading, message) {
  checkBtn.disabled = isLoading;
  checkImageBtn.disabled = isLoading;
  if (isLoading) {
    resultBox.className = "is-loading";
    resultBox.textContent = message;
  }
}

// fetch：用 JavaScript 向後端送資料，並等待回應
async function checkText() {
  const text = userText.value.trim();

  if (!text) {
    resultBox.className = "is-error";
    resultBox.textContent = "請先貼上可疑的文字或網址。";
    return;
  }

  setLoading(true, "文字分析中，請稍候...");

  try {
    const response = await fetch(apiUrl("/api/check"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ text: text })
    });

    const data = await response.json();
    resultBox.className = "";
    resultBox.textContent = data.result;
  } catch (error) {
    resultBox.className = "is-error";
    resultBox.textContent = "無法連線到伺服器。請確認後端已部署，且 config.js 的 API 網址正確。";
  }

  setLoading(false);
}

// FormData：專門用來上傳檔案（圖片）給後端
async function checkImage() {
  const file = userImage.files[0];

  if (!file) {
    resultBox.className = "is-error";
    resultBox.textContent = "請先選擇一張圖片。";
    return;
  }

  setLoading(true, "圖片分析中，請稍候...");

  try {
    const formData = new FormData();
    formData.append("image", file);

    const response = await fetch(apiUrl("/api/check-image"), {
      method: "POST",
      body: formData
    });

    const data = await response.json();
    resultBox.className = "";
    resultBox.textContent = data.result;
  } catch (error) {
    resultBox.className = "is-error";
    resultBox.textContent = "無法連線到伺服器。請確認後端已部署，且 config.js 的 API 網址正確。";
  }

  setLoading(false);
}

checkBtn.addEventListener("click", checkText);
checkImageBtn.addEventListener("click", checkImage);

clearBtn.addEventListener("click", function () {
  userText.value = "";
  userImage.value = "";
  resultBox.className = "";
  resultBox.textContent = "結果會顯示在這裡。";
  userText.focus();
});
