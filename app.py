"""
AICM Radar SP — Instagram Intelligence Agent
Flask web application for Railway deployment
"""

import os
import json
import time
import threading
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, request, jsonify
import anthropic
from apify_client import ApifyClient

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "radar-sp-secret-2026")

DATA_DIR = Path("data")
REPORTS_DIR = Path("reports")
CONFIG_FILE = DATA_DIR / "config.json"
DATA_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)

run_status = {
    "running": False, "logs": [], "progress": 0,
    "total": 0, "current_profile": "", "finished": False,
    "last_run": None, "error": None,
}

# ─── CONFIG ───────────────────────────────────────────────────────────────────
def load_config():
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {"my_profile": "", "specialty": "", "location": "São Paulo",
            "competitors": [], "apify_token": "", "anthropic_key": ""}

def save_config(config):
    CONFIG_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

# ─── SCRAPING ─────────────────────────────────────────────────────────────────
def scrape_profile(username, apify_token, max_posts=30):
    try:
        client = ApifyClient(apify_token)
        run_input = {"usernames": [username.lstrip("@")], "resultsLimit": max_posts}
        run = client.actor("apify/instagram-profile-scraper").call(run_input=run_input)
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
        return items[0] if items else None
    except Exception as e:
        return None

# ─── AI ANALYSIS ──────────────────────────────────────────────────────────────
def build_posts_summary(profile_data):
    posts = []
    for post in profile_data.get("posts", [])[:25]:
        posts.append({
            "caption": post.get("caption", "")[:400],
            "likes": post.get("likesCount", 0),
            "comments": post.get("commentsCount", 0),
            "type": post.get("type", ""),
            "date": str(post.get("timestamp", ""))[:10],
            "hashtags": post.get("hashtags", [])[:10],
        })
    return posts

def analyze_own_profile(profile_data, config, key):
    ai = anthropic.Anthropic(api_key=key)
    posts = build_posts_summary(profile_data)
    prompt = f"""Você é especialista em marketing médico digital e personal branding para médicos brasileiros.
Analise MEU PRÓPRIO perfil do Instagram com diagnóstico honesto e acionável.

PERFIL: {profile_data.get('fullName')} | @{profile_data.get('username')}
Bio: {profile_data.get('biography')}
Seguidores: {profile_data.get('followersCount',0):,} | Posts: {profile_data.get('postsCount',0)}
Especialidade: {config.get('specialty','Médico')} | Cidade: {config.get('location','SP')}

ÚLTIMOS POSTS:
{json.dumps(posts, ensure_ascii=False, indent=2)}

Forneça:
### 1. DIAGNÓSTICO GERAL
Nota 0-10 com justificativa. Clareza de posicionamento. Eficácia da bio.

### 2. ANÁLISE POST A POST
Para cada post: tema, tipo, performance, o que funcionou, o que melhorar.

### 3. PADRÕES IDENTIFICADOS
Temas que mais engajam. Tipos de post com melhor performance. Frequência. Hashtags.

### 4. PONTOS FORTES
O que fazer mais.

### 5. PONTOS DE MELHORIA
O que mudar, em ordem de prioridade.

### 6. TOP 5 AÇÕES — PRÓXIMOS 30 DIAS
Ações concretas e implementáveis.

Responda em português, direto e profissional."""
    msg = ai.messages.create(model="claude-opus-4-6", max_tokens=3000,
                              messages=[{"role": "user", "content": prompt}])
    return msg.content[0].text

def analyze_competitor(profile_data, config, key):
    ai = anthropic.Anthropic(api_key=key)
    posts = build_posts_summary(profile_data)
    prompt = f"""Você é especialista em marketing médico digital e inteligência competitiva.
Analise este CONCORRENTE e gere relatório de inteligência competitiva.

PERFIL: {profile_data.get('fullName')} | @{profile_data.get('username')}
Bio: {profile_data.get('biography')}
Seguidores: {profile_data.get('followersCount',0):,} | Posts: {profile_data.get('postsCount',0)}
Minha especialidade: {config.get('specialty','Médico')} | Cidade: {config.get('location','SP')}

POSTS:
{json.dumps(posts, ensure_ascii=False, indent=2)}

Forneça:
### 1. PERFIL ESTRATÉGICO
Posicionamento, nicho, proposta de valor, público-alvo. Nível de ameaça 1-10.

### 2. ANÁLISE DOS POSTS
Tema, tipo, performance, por que funcionou ou não.

### 3. ESTRATÉGIA DE CONTEÚDO
Temas mais engajados, mix de conteúdo, tom, frequência, hashtags.

### 4. PONTOS FORTES DO CONCORRENTE
O que aprender.

### 5. LACUNAS E OPORTUNIDADES
O que ele não faz — suas oportunidades.

### 6. INSIGHTS ACIONÁVEIS
O que implementar para se diferenciar.

Responda em português, direto e analítico."""
    msg = ai.messages.create(model="claude-opus-4-6", max_tokens=3000,
                              messages=[{"role": "user", "content": prompt}])
    return msg.content[0].text

def generate_content_plan(all_analyses, config, key):
    ai = anthropic.Anthropic(api_key=key)
    summaries = [{"perfil": a["username"], "seguidores": a["followers"],
                  "analise": a["analysis"][:800]}
                 for a in all_analyses if a["type"] == "competitor"]
    prompt = f"""Você é estrategista de conteúdo especializado em marketing médico digital no Brasil.
Crie PLANO DE CONTEÚDO estratégico baseado nas análises dos concorrentes.

MEU PERFIL: @{config.get('my_profile','')} | {config.get('specialty','Médico')} | {config.get('location','SP')}

CONCORRENTES ANALISADOS:
{json.dumps(summaries, ensure_ascii=False, indent=2)}

Forneça:
### 1. TOP 10 TEMAS QUE MAIS ENGAJAM NO MERCADO
Com justificativa baseada nos dados.

### 2. PLANO — PRÓXIMAS 4 SEMANAS
Por semana, 3 posts com: tema, formato (Reels/Carrossel/Foto/Stories), headline, pontos principais, hashtags, por que tem potencial.

### 3. FORMATOS QUE MAIS PERFORMAM
Ranking com justificativa.

### 4. ESTRATÉGIA DE DIFERENCIAÇÃO
Como se destacar dos concorrentes.

### 5. CALENDÁRIO SUGERIDO
Frequência, melhores dias e horários.

Responda em português, específico e prático."""
    msg = ai.messages.create(model="claude-opus-4-6", max_tokens=3500,
                              messages=[{"role": "user", "content": prompt}])
    return msg.content[0].text

def generate_executive_summary(all_analyses, config, key):
    ai = anthropic.Anthropic(api_key=key)
    summaries = [{"tipo": a["type"], "perfil": a["username"],
                  "seguidores": a["followers"], "resumo": a["analysis"][:600]}
                 for a in all_analyses]
    prompt = f"""Crie RELATÓRIO EXECUTIVO consolidando toda a inteligência coletada.

{len(all_analyses)} perfis analisados | @{config.get('my_profile')} | {config.get('specialty')} | {datetime.now().strftime('%d/%m/%Y')}

ANÁLISES:
{json.dumps(summaries, ensure_ascii=False, indent=2)}

Forneça (máx 700 palavras):
### PANORAMA COMPETITIVO
Situação atual do mercado no Instagram nesta especialidade em SP.

### POSIÇÃO COMPETITIVA ATUAL
Onde você está em relação aos concorrentes.

### 3 PRIORIDADES IMEDIATAS
As 3 ações mais importantes para fazer agora.

### OPORTUNIDADES DE MERCADO
O que nenhum concorrente está fazendo bem.

### PLANO 90 DIAS
Timeline com marcos claros.

Seja direto, executivo, sem rodeios."""
    msg = ai.messages.create(model="claude-opus-4-6", max_tokens=2000,
                              messages=[{"role": "user", "content": prompt}])
    return msg.content[0].text

# ─── BACKGROUND RUNNER ────────────────────────────────────────────────────────
def run_analysis_thread(config):
    global run_status
    run_status.update({"running": True, "logs": [], "finished": False,
                       "error": None, "progress": 0})

    apify_token = config.get("apify_token") or os.getenv("APIFY_TOKEN", "")
    anthropic_key = config.get("anthropic_key") or os.getenv("ANTHROPIC_API_KEY", "")

    def log(msg, level="info"):
        run_status["logs"].append({
            "msg": msg, "level": level,
            "time": datetime.now().strftime("%H:%M:%S")
        })

    try:
        profiles = [{"username": config["my_profile"], "type": "own"}]
        profiles += [{"username": c, "type": "competitor"} for c in config.get("competitors", [])]
        run_status["total"] = len(profiles)
        all_analyses = []

        for i, p in enumerate(profiles):
            username = p["username"].lstrip("@")
            label = "MEU PERFIL" if p["type"] == "own" else "CONCORRENTE"
            run_status.update({"current_profile": username, "progress": i})
            log(f"[{label}] Coletando @{username}...", "info")

            data = scrape_profile(username, apify_token)
            if not data:
                log(f"⚠️  @{username} — sem dados", "warn")
                continue

            followers = data.get("followersCount", 0)
            log(f"✅ @{username} — {followers:,} seguidores · {len(data.get('posts',[]))} posts", "success")
            log(f"🤖 Analisando @{username} com IA...", "info")

            analysis = analyze_own_profile(data, config, anthropic_key) if p["type"] == "own" \
                       else analyze_competitor(data, config, anthropic_key)

            all_analyses.append({
                "type": p["type"], "username": username,
                "full_name": data.get("fullName", username),
                "followers": followers,
                "posts_analyzed": len(data.get("posts", [])),
                "analysis": analysis,
                "collected_at": datetime.now().isoformat(),
            })
            log(f"✅ Análise de @{username} concluída", "success")
            time.sleep(1)

        content_plan = exec_summary = "Sem dados suficientes."
        if all_analyses:
            log("💡 Gerando plano de conteúdo...", "info")
            content_plan = generate_content_plan(all_analyses, config, anthropic_key)
            log("✅ Plano de conteúdo gerado", "success")
            log("📋 Gerando relatório executivo...", "info")
            exec_summary = generate_executive_summary(all_analyses, config, anthropic_key)
            log("✅ Relatório executivo gerado", "success")

        date_str = datetime.now().strftime("%Y%m%d_%H%M")
        report = {
            "id": date_str,
            "run_date": datetime.now().isoformat(),
            "run_date_br": datetime.now().strftime("%d/%m/%Y às %H:%M"),
            "config": {k: v for k, v in config.items() if "token" not in k and "key" not in k},
            "profiles_analyzed": len(all_analyses),
            "analyses": all_analyses,
            "content_plan": content_plan,
            "executive_summary": exec_summary,
        }
        (REPORTS_DIR / f"{date_str}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

        run_status.update({"progress": run_status["total"], "last_run": date_str})
        log(f"🎉 Concluído! {len(all_analyses)} perfis analisados.", "success")

    except Exception as e:
        run_status["error"] = str(e)
        log(f"❌ Erro: {e}", "error")
    finally:
        run_status.update({"running": False, "finished": True})

# ─── ROUTES ───────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html", config=load_config(), reports=get_reports_list())

@app.route("/api/config", methods=["GET"])
def api_get_config():
    return jsonify(load_config())

@app.route("/api/config", methods=["POST"])
def api_save_config():
    config = load_config()
    config.update(request.json)
    save_config(config)
    return jsonify({"ok": True})

@app.route("/api/run", methods=["POST"])
def api_run():
    if run_status["running"]:
        return jsonify({"ok": False, "error": "Análise já em andamento"})
    config = load_config()
    if not config.get("my_profile"):
        return jsonify({"ok": False, "error": "Configure seu perfil primeiro"})
    threading.Thread(target=run_analysis_thread, args=(config,), daemon=True).start()
    return jsonify({"ok": True})

@app.route("/api/status")
def api_status():
    return jsonify(run_status)

@app.route("/api/reports")
def api_reports():
    return jsonify(get_reports_list())

@app.route("/api/report/<report_id>")
def api_report(report_id):
    path = REPORTS_DIR / f"{report_id}.json"
    if not path.exists():
        return jsonify({"error": "Não encontrado"}), 404
    return jsonify(json.loads(path.read_text(encoding="utf-8")))

def get_reports_list():
    reports = []
    for f in sorted(REPORTS_DIR.glob("*.json"), reverse=True):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            reports.append({
                "id": d["id"], "run_date_br": d.get("run_date_br", d["id"]),
                "profiles_analyzed": d.get("profiles_analyzed", 0),
                "my_profile": d.get("config", {}).get("my_profile", ""),
                "competitors": d.get("config", {}).get("competitors", []),
            })
        except: pass
    return reports

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False)
