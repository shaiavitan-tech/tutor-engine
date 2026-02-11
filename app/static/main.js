// ==================== מצב כללי ====================

let currentSessionId = null;
let currentSubject = null; // "english" | "math" | "geometry" | null

let pendingExercises = [];      // רשימת תרגילים/משימות מהתמונה
let currentExerciseIndex = -1;  // אינדקס תרגיל נוכחי ב-pendingExercises
let waitingForExerciseConfirm = false; // האם מחכים ל"כן/לא" על תרגיל מזוהה

// אלמנטים
const studentMessageInput = document.getElementById("studentMessage");
const chatLog = document.getElementById("chatLog");

const subjectPicker = document.getElementById("subjectPicker");
const subjectEnglishBtn = document.getElementById("subjectEnglish");
const subjectMathBtn = document.getElementById("subjectMath");
const subjectGeometryBtn = document.getElementById("subjectGeometry");

const cameraInput = document.getElementById("cameraInput");
const fileInput = document.getElementById("fileInput");

const exerciseConfirmButtons = document.getElementById("exerciseConfirmButtons");
const exerciseYesBtn = document.getElementById("exerciseYesBtn");
const exerciseNoBtn = document.getElementById("exerciseNoBtn");

function showExerciseConfirmButtons() {
  if (exerciseConfirmButtons) exerciseConfirmButtons.style.display = "flex";
}

function hideExerciseConfirmButtons() {
  if (exerciseConfirmButtons) exerciseConfirmButtons.style.display = "none";
}

// ==================== עזר UI ====================

function appendMessage(sender, text) {
  const div = document.createElement("div");
  div.className = `message ${sender}`;

  const roleSpan = document.createElement("div");
  roleSpan.className = "role";
  roleSpan.textContent = sender === "student" ? "שירה" : "העוזר";

  const textDiv = document.createElement("div");

  const trimmed = text.trim();
  const looksLikeExercise =
    /^[0-9+\-×÷*/()=?\s]+$/.test(trimmed) && trimmed.length <= 40;

  if (looksLikeExercise) {
    div.classList.add("only-math"); // כל הבועה הופכת ל‑LTR
    textDiv.textContent = trimmed;
  } else {
    textDiv.textContent = text;
  }

  div.appendChild(roleSpan);
  div.appendChild(textDiv);
  chatLog.appendChild(div);
  chatLog.scrollTop = chatLog.scrollHeight;
}

function updateLastTutorMessage(text) {
  const trimmed = text.trim();
  const looksLikeExercise =
    /^[0-9+\-×÷*/()=?\s]+$/.test(trimmed) && trimmed.length <= 40;

  for (let i = chatLog.children.length - 1; i >= 0; i--) {
    const node = chatLog.children[i];
    if (node.classList.contains("tutor")) {
      const bubble = node.lastChild;

      if (looksLikeExercise) {
        node.classList.add("only-math");
        bubble.textContent = trimmed;
      } else {
        bubble.textContent = text;
      }

      chatLog.scrollTop = chatLog.scrollHeight;
      return;
    }
  }
}

// סטרימינג – תמיד משתמש ב-/stream/*
async function streamFromEndpoint(url, body, onFullText) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!resp.body) {
    const text = await resp.text();
    onFullText(text);
    return;
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let fullText = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    const chunk = decoder.decode(value, { stream: true });
    fullText += chunk;
    updateLastTutorMessage(fullText);
  }

  onFullText(fullText);

  // --- לופ תרגילים מהתמונה ---

  // זיהוי סיום תרגיל (הטוטור מציע עוד תרגיל)
  const wantMoreRegex = /רוצה[^.!?]{0,30}עוד[^.!?]{0,30}תרגיל/;

  // יש עוד תרגילים בסט -> עוברים לתרגיל הבא
  if (
    url === "/stream/check" &&
    pendingExercises.length > 0 &&
    currentExerciseIndex >= 0 &&
    currentExerciseIndex < pendingExercises.length - 1 &&
    wantMoreRegex.test(fullText)
  ) {
    currentExerciseIndex += 1;
    currentSessionId = null;

    const nextEx = pendingExercises[currentExerciseIndex];

    // בועה לטקסט
    appendMessage(
      "tutor",
      "מעולה! עכשיו נעבור לתרגיל הבא מהתמונה:"
    );
    // בועה נפרדת רק לתרגיל – תוצג כ-only-math
    appendMessage("tutor", nextEx);
    // שאלה
    appendMessage(
      "tutor",
      "האם זה התרגיל הבא שאת רוצה לפתור?"
    );

    waitingForExerciseConfirm = true;
    showExerciseConfirmButtons();
    return;
  }

  // זה היה התרגיל האחרון בסט -> סוגרים לופ ומציעים עזרה כללית
  if (
    url === "/stream/check" &&
    pendingExercises.length > 0 &&
    currentExerciseIndex === pendingExercises.length - 1 &&
    wantMoreRegex.test(fullText)
  ) {
    pendingExercises = [];
    currentExerciseIndex = -1;
    currentSessionId = null;
    waitingForExerciseConfirm = false;
    hideExerciseConfirmButtons();

    appendMessage(
      "tutor",
      "כל הכבוד שירה, פתרנו את כל התרגילים מהתמונה! " +
        "אם את רוצה, אפשר לעבוד עכשיו על תרגילים נוספים או על נושא אחר."
    );
  }
}


// ==================== Flow שיחה ====================

function startInitialConversation() {
  appendMessage("tutor", "שלום שירה, אני העוזר הלימודי האישי שלך.");
  appendMessage(
    "tutor",
    "בחרי נושא ללמידה: אנגלית, חשבון או גאומטריה (לחיצה על אחד הכפתורים)."
  );
}

function selectSubject(subject) {
  currentSubject = subject;
  if (subjectPicker) subjectPicker.style.display = "none";

  if (subject === "english") {
    appendMessage(
      "tutor",
      "Great! What would you like to practice in English? (grammar, vocabulary, writing) (במה באנגלית תרצי לתרגל – דקדוק, אוצר מילים או כתיבה?)"
    );
  } else if (subject === "math") {
    appendMessage(
      "tutor",
      "מעולה! כתבי לי כאן את התרגיל בחשבון (למשל 2x + 3 = 11) או לחצי על 📷 צלמי תרגיל כדי להעלות תמונה."
    );
  } else if (subject === "geometry") {
    appendMessage(
      "tutor",
      "נהדר! כתבי כאן את התרגיל בגאומטריה או לחצי על 📷 צלמי תרגיל כדי להעלות תמונה."
    );
  }
}

async function handleStudentMessageSend(isFinalAnswer = false) {
  const msg = studentMessageInput.value.trim();
  if (!msg) return;

  appendMessage("student", msg);
  studentMessageInput.value = "";

  // אם היינו במצב של "לא" על תרגיל מזוהה – ההודעה הזו היא התרגיל החדש
  if (!currentSessionId && currentExerciseIndex >= 0 && !waitingForExerciseConfirm) {
    await startExerciseFromText(msg);
    return;
  }

  if (!currentSubject) {
    appendMessage(
      "tutor",
      "קודם בחרי נושא: אנגלית, חשבון או גאומטריה."
    );
    return;
  }

  // אם אין session – ההודעה הראשונה היא התרגיל
  if (!currentSessionId) {
    await startExerciseFromText(msg);
    return;
  }

  // אם יש session – סטרימינג לרמז / לבדיקה
  if (!isFinalAnswer) {
    appendMessage("tutor", "העוזר חושב על רמז מתאים...");
    await streamFromEndpoint(
      "/stream/hint",
      {
        session_id: currentSessionId,
        student_message: msg,
      },
      () => {}
    );
  } else {
    appendMessage("tutor", "בודק/ת את התשובה שלך...");
    await streamFromEndpoint(
      "/stream/check",
      {
        session_id: currentSessionId,
        student_answer: msg,
      },
      () => {}
    );
  }
}

// פתיחת תרגיל מטקסט – non-stream (תשובה ראשונה קצרה)
async function startExerciseFromText(text) {
  const studentName = "Shira";
  const questionText = (text || "").trim();
  if (!questionText) return;

  const resp = await fetch("/exercises/start_from_text", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ student_name: studentName, question_text: questionText }),
  });

  const data = await resp.json();
  console.log("start_from_text response:", data);

  if (!data.allowed) {
    appendMessage("tutor", data.message || "השאלה לא בתחום אנגלית/מתמטיקה.");
    return;
  }

  currentSessionId = data.session_id;
  console.log("currentSessionId set to:", currentSessionId);

  appendMessage("tutor", data.hint_text);
}

// פתיחת תרגיל מתמונה
async function startExerciseFromImage(file) {
  const studentName = "Shira";
  if (!file) return;

  appendMessage("student", "[שירה העלתה תמונה]");

  if (!currentSubject) {
    appendMessage(
      "tutor",
      "קודם בחרי נושא (אנגלית / חשבון / גאומטריה), ואז נפתור את התרגילים מהתמונה."
    );
    return;
  }

  const formData = new FormData();
  formData.append("student_name", studentName);
  formData.append("file", file);

  const resp = await fetch("/exercises/start_from_image", {
    method: "POST",
    body: formData,
  });

  const data = await resp.json();
  if (!data.allowed) {
    appendMessage("tutor", data.message || "לא הצלחתי לזהות תרגילים מהתמונה.");
    return;
  }

  // ננקה state קודם
  pendingExercises = [];
  currentExerciseIndex = -1;
  waitingForExerciseConfirm = false;
  hideExerciseConfirmButtons();

  // --- חשבון / גאומטריה (subject="math") ---
  if (data.subject === "math") {
    pendingExercises = Array.isArray(data.exercises) ? data.exercises : [];

    if (!pendingExercises.length) {
      appendMessage(
        "tutor",
        "זיהיתי שזה דף בחשבון, אבל לא הצלחתי להוציא ממנו תרגילים. כתבי לי תרגיל אחד כאן."
      );
      return;
    }

    // נתחיל מהתרגיל הראשון: קודם מאשרים עם כן/לא
    currentExerciseIndex = 0;
    currentSessionId = null;

    const ex = pendingExercises[currentExerciseIndex];
    const ex = pendingExercises[currentExerciseIndex];

    appendMessage(
      "tutor",
      "זיהיתי בתמונה את התרגיל הראשון:"
    );

    // בועה נפרדת רק לתרגיל – תזוהה כ-looksLikeExercise ותהפוך ל-only-math (LTR)
    appendMessage("tutor", ex);

    appendMessage(
      "tutor",
      "האם זה התרגיל שאת רוצה לפתור עכשיו?"
    );

    waitingForExerciseConfirm = true;
    showExerciseConfirmButtons();

    return;
  }

  // --- אנגלית (subject="english") ---
  if (data.subject === "english") {
    if (data.tasks_summary) {
      appendMessage("tutor", data.tasks_summary);
    }

    pendingExercises = Array.isArray(data.tasks) ? data.tasks : [];
    currentExerciseIndex = 0;
    currentSessionId = null;

    if (pendingExercises.length) {
      const firstTask = pendingExercises[0];
      appendMessage(
        "tutor",
        `נתחיל מהתרגיל באנגלית שזיהיתי:\n${firstTask}\nכתבי לי מה לדעתך צריך לעשות כאן או את התשובה שלך.`
      );
    } else {
      appendMessage(
        "tutor",
        "זיהיתי דף באנגלית, אבל לא הצלחתי לפצל למשימות. נסי לכתוב לי כאן את השאלה הראשונה, ונפתור אותה יחד."
      );
    }

    return;
  }

  // --- כל מקרה אחר ---
  appendMessage(
    "tutor",
    data.message ||
      "אני עוזר רק באנגלית וחשבון. נסי להעלות תמונה של דף תרגילים באנגלית או בחשבון."
  );
}

// ==================== חיבור אירועים ====================

// בחירת נושא
subjectEnglishBtn.addEventListener("click", () => selectSubject("english"));
subjectMathBtn.addEventListener("click", () => selectSubject("math"));
subjectGeometryBtn.addEventListener("click", () => selectSubject("geometry"));

// Enter בשדה ההודעה
studentMessageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    handleStudentMessageSend(false);
  }
});

// כפתור צילום / העלאת תמונה
// צילום במצלמה
cameraInput.addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;

  if (!currentSubject) {
    appendMessage(
      "tutor",
      "קודם בחרי נושא (אנגלית / חשבון / גאומטריה), ואז נפתור את התרגיל מהתמונה."
    );
    cameraInput.value = "";
    return;
  }

  await startExerciseFromImage(file);
  cameraInput.value = "";
});

// העלאת קובץ קיים
fileInput.addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;

  if (!currentSubject) {
    appendMessage(
      "tutor",
      "קודם בחרי נושא (אנגלית / חשבון / גאומטריה), ואז נפתור את התרגיל מהתמונה."
    );
    fileInput.value = "";
    return;
  }

  await startExerciseFromImage(file);
  fileInput.value = "";
});

// בעת טעינת הדף
window.addEventListener("load", () => {
  startInitialConversation();
});

// אישור תרגיל מזוהה מהתמונה
exerciseYesBtn.addEventListener("click", async () => {
  if (!waitingForExerciseConfirm || currentExerciseIndex < 0) return;

  const ex = pendingExercises[currentExerciseIndex];

  waitingForExerciseConfirm = false;
  hideExerciseConfirmButtons();
  appendMessage("student", "כן");

  // מתחילים תרגיל חדש מהטקסט שזוהה
  await startExerciseFromText(ex);
});

// דחיית תרגיל מזוהה – שירה תקיש את התרגיל בעצמה
exerciseNoBtn.addEventListener("click", () => {
  if (!waitingForExerciseConfirm || currentExerciseIndex < 0) return;

  const ex = pendingExercises[currentExerciseIndex];

  waitingForExerciseConfirm = false;
  hideExerciseConfirmButtons();
  appendMessage("student", "לא");

  appendMessage(
    "tutor",
    `הבנתי, כנראה טעיתי בזיהוי. כתבי לי כאן את התרגיל במקום:\n${ex}\nואז נתחיל לפתור אותו.`
  );
});
