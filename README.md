# 🤖 PretendAI

<p align="center">
  <img src="assets/ai-banner.png" alt="PretendAI Banner">
</p>

<p align="center">
  <b>The Reverse Turing Test</b>
  <br>
  AI pretends to be human. You pretend to be AI.
</p>

<p align="center">
  <a href="https://pretendai.vercel.app">
    <img src="https://img.shields.io/badge/🌐_Live_Demo-Try_PretendAI-000?style=for-the-badge">
  </a>
</p>

---

## 💡 About

After spending years chatting with AI assistants, I started wondering:

> **Have we actually learned how AI thinks?**

Most people can recognize a good AI response.

Far fewer can consistently produce one.

So I built **PretendAI** — a reverse Turing Test where humans attempt to act like AI assistants while AI models pretend to be human users.

The challenge is simple:

* 🤖 AI acts as the user
* 🧑 You act as the AI assistant
* 🧠 Another AI evaluates the conversation

At the end of every session, you receive a detailed score and feedback explaining how AI-like your responses were.

---

## 🎮 How It Works

```text
AI User
   │
   ▼
Human Player (acts as AI)
   │
   ▼
AI Judge
   │
   ▼
Score + Feedback + Leaderboard
```

1. Choose a mode
2. Start chatting with an AI pretending to be a human
3. Respond exactly like an AI assistant
4. Complete the session
5. Receive AI-generated feedback
6. Share your scorecard and compare results

---

## 🎭 Game Modes

| Mode         | Description                                                              |
| ------------ | ------------------------------------------------------------------------ |
| 🎯 Classic   | Everyday conversations involving coding, writing, productivity, and life |
| 🎭 Interview | Character-driven conversations with personalities and goals              |
| 🌪️ Chaos    | Surreal, unpredictable, and absurd scenarios                             |
| 🔓 Jailbreak | AI actively attempts to break your character                             |

---

## 📊 Evaluation Categories

Every conversation is analyzed across multiple dimensions.

| Metric                       | Description                                   |
| ---------------------------- | --------------------------------------------- |
| 🤝 Helpfulness               | Did you help the user?                        |
| 📝 Clarity                   | Were responses easy to understand?            |
| 🏗️ Structure                | Were responses organized and readable?        |
| ⚖️ Neutrality                | Did you avoid unnecessary bias?               |
| 🎯 Accuracy                  | Were responses reliable?                      |
| 🤖 AI-Likeness               | How closely did you resemble an AI assistant? |
| ❤️ Empathy                   | Did you appropriately acknowledge concerns?   |
| 🛡️ Hallucination Resistance | Did you avoid unsupported claims?             |

The evaluation engine generates:

* Final score (0–100)
* Detailed feedback
* Strengths
* Weaknesses
* Improvement suggestions

---

## 📸 Shareable Scorecards

Every completed session generates a dynamic scorecard.

<p align="center">
  <img src="assets/scorecard.png" width="900" alt="PretendAI Scorecard">
</p>

Example feedback:

```text
Score: 55/100

Strengths
✓ Helpful tone
✓ Mostly neutral responses
✓ Acknowledged user concerns

Weaknesses
✗ Too generic
✗ Not specific enough
✗ Failed to deeply understand the user's project
```

These scorecards can be shared on social platforms and used to challenge friends.

---

## ✨ Features

* 🤖 Reverse Turing Test gameplay
* 🧠 AI-generated conversations
* 📊 AI-powered evaluation system
* 🏆 Global leaderboard
* 📸 Dynamic scorecard generation
* ⏱️ Timed sessions
* 🎭 Multiple game modes
* 🔓 Jailbreak challenges
* 🌍 Public rankings
* 📈 Detailed performance analytics

---

## 🏗️ Tech Stack

<p align="center">
  <img src="https://skillicons.dev/icons?i=python,flask,mongodb,html,css,js,vercel&perline=7" />
</p>

### Frontend

* HTML5
* CSS3
* Vanilla JavaScript

### Backend

* Python
* Flask

### Database

* MongoDB

### AI

* Groq API
* LLM-powered conversation engine
* LLM-powered evaluation engine

### Deployment

* Vercel

---

## 🧠 System Architecture

```text
Player
  │
  ▼
Frontend (HTML/CSS/JS)
  │
  ▼
Flask Backend
  │
  ├── MongoDB
  │
  ├── Conversation Engine
  │
  │      └── Groq API
  │
  └── Evaluation Engine
         └── Groq API
                 │
                 ▼
           Score Generator
                 │
                 ▼
            Leaderboard
```

---

## ⚙️ Reliability Engineering

One challenge was handling occasional model failures and request timeouts.

To improve reliability, PretendAI automatically falls back to alternative models when necessary.

```python
FALLBACK_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "gemma2-9b-it",
]
```

If a model fails, times out, or becomes unavailable, the system automatically retries using the next available model.

This ensures conversations continue without disrupting the user experience.

---

## 📸 Dynamic Image Generation

PretendAI generates scorecards automatically after every session.

Instead of manually creating images, scorecards are rendered using HTML and CSS and then converted into PNG images.

Benefits:

* Reusable frontend components
* Dynamic data rendering
* Social-media-ready graphics
* Consistent visual design

This approach made it possible to generate personalized scorecards directly from evaluation results.

---

## 🚀 Getting Started

### Clone Repository

```bash
git clone https://github.com/MKishoreDev/PretendAi.git

cd PretendAi
```

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Configure Environment Variables

Create a `.env` file:

```env
GROQ_API_KEY=your_groq_api_key
MONGODB_URI=your_mongodb_uri
```

### Run Locally

```bash
python app.py
```

Open:

```text
http://localhost:5000
```

---

## 🤝 Contributing

Contributions, ideas, feature requests, and bug reports are welcome.

Feel free to open an issue or submit a pull request.

---

## ⭐ Support

If you find PretendAI interesting, consider giving it a star.

It helps more people discover the project and supports future development.

---

<p align="center">
  <b>Think you understand AI?</b>
  <br>
  Prove it.
</p>
