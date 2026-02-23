"""
Instagram Intelligence Agent
Flask web application — Universal, works for any niche
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
app.secret_key = os.getenv("SECRET_KEY", "radar-ig-secret-2026")

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

def load_config():
    env_comp = os.getenv("COMPETITORS", "")
    config = {
        "my_profile":    os.getenv("MY_PROFILE", ""),
        "niche":         os.getenv("MY_NICHE", ""),
        "location":      os.getenv("MY_LOCATION", ""),
        "competitors":   [c.strip() for c in env_comp.split(",") if c.strip()] if env_comp else [],
        "apify_token":   os.getenv("APIFY_TOKEN", ""),
        "anthropic_key": os.getenv("ANTHROPIC_API_KEY", ""),
    }
    if CONFIG_FILE.exists():
        try:
            saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            for k, v in saved.items():
                if v or v == []:
                    config[k] = v
        except:
            pass
    return config

def save_config(config):
    CONFIG_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

def scrape_profile(username, apify_token, max_posts=30):
    """Scrape Instagram profile + posts using apify/instagram-profile-scraper"""
    client = ApifyClient(apify_token)
    uname = username.lstrip("@")

    # Step 1: Get profile data
    try:
        profile_run = client.actor("apify/instagram-profile-scraper").call(run_input={
            "usernames": [uname],
        })
        profile_items = list(client.dataset(profile_run["defaultDatasetId"]).iterate_items())
    except Exception as e:
        raise Exception(f"Erro Apify (perfil) para @{uname}: {str(e)}")

    if not profile_items:
        raise Exception(f"Perfil @{uname} não encontrado ou privado")

    profile = profile_items[0]

    # Step 2: Get posts separately
    try:
        posts_run = client.actor("apify/instagram-scraper").call(run_input={
            "directUrls": [f"https://www.instagram.com/{uname}/"],
            "resultsType": "posts",
            "resultsLimit": max_posts,
            "proxy": {"useApifyProxy": True},
        })
        posts = list(client.dataset(posts_run["defaultDatasetId"]).iterate_items())
        profile["posts"] = posts
    except Exception:
        # Posts failed but profile OK — continue with empty posts
        profile["posts"] = profile.get("latestPosts", [])

    return profile

def detect_niche(profile_data, key):
    ai = anthropic.Anthropic(api_key=key)
    posts = [p.get("caption", "")[:200] for p in profile_data.get("posts", [])[:8]]
    prompt = f"""Analise este perfil do Instagram e identifique em UMA frase curta o nicho/área de atuação.
Bio: {profile_data.get('biography', '')}
Nome: {profile_data.get('fullName', '')}
Posts recentes: {json.dumps(posts, ensure_ascii=False)}
Responda APENAS com o nicho em uma frase curta. Ex: "Coach de emagrecimento", "Advogado tributarista", "Personal trainer", "Chef de cozinha vegana". Seja específico."""
    msg = ai.messages.create(model="claude-opus-4-6", max_tokens=50,
                              messages=[{"role": "user", "content": prompt}])
    return msg.content[0].text.strip()

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

def analyze_own_profile(profile_data, config, key, detected_niche):
    ai = anthropic.Anthropic(api_key=key)
    posts = build_posts_summary(profile_data)
    niche = detected_niche or config.get("niche", "criador de conteúdo")
    loc = f" em {config['location']}" if config.get("location") else ""
    prompt = f"""Você é especialista em marketing digital e estratégia de conteúdo para Instagram.
Analise MEU PRÓPRIO perfil com diagnóstico honesto e acionável.
Nicho identificado: {niche}{loc}

PERFIL: {profile_data.get('fullName')} | @{profile_data.get('username')}
Bio: {profile_data.get('biography')}
Seguidores: {profile_data.get('followersCount',0):,} | Posts: {profile_data.get('postsCount',0)}

ÚLTIMOS POSTS:
{json.dumps(posts, ensure_ascii=False, indent=2)}

### 1. DIAGNÓSTICO GERAL
Nota 0-10 com justificativa. Clareza do posicionamento no nicho "{niche}". Eficácia da bio.

### 2. ANÁLISE POST A POST
Para cada post: tema, tipo, performance (likes+comentários), o que funcionou, o que melhorar.

### 3. PADRÕES IDENTIFICADOS
Temas que mais engajam. Tipos de post com melhor performance. Frequência. Hashtags.

### 4. PONTOS FORTES
O que fazer mais.

### 5. PONTOS DE MELHORIA
O que mudar, em ordem de prioridade e impacto.

### 6. TOP 5 AÇÕES — PRÓXIMOS 30 DIAS
Ações concretas e implementáveis para crescer no nicho {niche}.

Responda em português, direto e profissional."""
    msg = ai.messages.create(model="claude-opus-4-6", max_tokens=3000,
                              messages=[{"role": "user", "content": prompt}])
    return msg.content[0].text

def analyze_competitor(profile_data, config, key, my_niche, comp_niche):
    ai = anthropic.Anthropic(api_key=key)
    posts = build_posts_summary(profile_data)
    loc = f" em {config['location']}" if config.get("location") else ""
    prompt = f"""Você é especialista em inteligência competitiva e estratégia de conteúdo para Instagram.
Analise este CONCORRENTE e gere relatório de inteligência competitiva.
Meu nicho: {my_niche}{loc}
Nicho do concorrente: {comp_niche}

PERFIL: {profile_data.get('fullName')} | @{profile_data.get('username')}
Bio: {profile_data.get('biography')}
Seguidores: {profile_data.get('followersCount',0):,} | Posts: {profile_data.get('postsCount',0)}

POSTS:
{json.dumps(posts, ensure_ascii=False, indent=2)}

### 1. PERFIL ESTRATÉGICO
Posicionamento e nicho. Proposta de valor. Público-alvo. Nível de ameaça 1-10 com justificativa.

### 2. ANÁLISE DOS POSTS
Para cada post relevante: tema, tipo, performance, por que funcionou ou não.

### 3. ESTRATÉGIA DE CONTEÚDO
Temas mais engajados. Mix de conteúdo. Tom. Frequência. Hashtags.

### 4. PONTOS FORTES
O que ele faz bem — o que aprender.

### 5. LACUNAS E OPORTUNIDADES
O que ele não faz — suas oportunidades.

### 6. INSIGHTS ACIONÁVEIS
O que implementar para se diferenciar (sem copiar).

Responda em português, direto e analítico."""
    msg = ai.messages.create(model="claude-opus-4-6", max_tokens=3000,
                              messages=[{"role": "user", "content": prompt}])
    return msg.content[0].text

def generate_content_plan(all_analyses, config, key, my_niche):
    ai = anthropic.Anthropic(api_key=key)
    summaries = [{"perfil": a["username"], "nicho": a.get("detected_niche",""),
                  "seguidores": a["followers"], "analise": a["analysis"][:800]}
                 for a in all_analyses if a["type"] == "competitor"]
    loc = f" em {config['location']}" if config.get("location") else ""
    prompt = f"""Você é estrategista de conteúdo especializado em Instagram e growth digital.
Crie um PLANO DE CONTEÚDO estratégico baseado nas análises dos concorrentes.

MEU PERFIL: @{config.get('my_profile','')} | Nicho: {my_niche}{loc}

CONCORRENTES ANALISADOS:
{json.dumps(summaries, ensure_ascii=False, indent=2)}

### 1. TOP 10 TEMAS QUE MAIS ENGAJAM NESTE NICHO
Com justificativa baseada nos dados reais dos concorrentes.

### 2. PLANO — PRÓXIMAS 4 SEMANAS
Por semana, 3 posts com: tema específico, formato (Reels/Carrossel/Foto/Stories), gancho/headline, pontos principais, hashtags sugeridas, por que tem potencial.

### 3. FORMATOS QUE MAIS PERFORMAM
Ranking com justificativa baseada nos dados.

### 4. ESTRATÉGIA DE DIFERENCIAÇÃO
Como se destacar com conteúdo único e autêntico.

### 5. CALENDÁRIO SUGERIDO
Frequência ideal, melhores dias e horários.

Responda em português, específico e implementável."""
    msg = ai.messages.create(model="claude-opus-4-6", max_tokens=3500,
                              messages=[{"role": "user", "content": prompt}])
    return msg.content[0].text

def generate_executive_summary(all_analyses, config, key, my_niche):
    ai = anthropic.Anthropic(api_key=key)
    summaries = [{"tipo": a["type"], "perfil": a["username"],
                  "nicho": a.get("detected_niche",""), "seguidores": a["followers"],
                  "resumo": a["analysis"][:600]}
                 for a in all_analyses]
    loc = f" em {config['location']}" if config.get("location") else ""
    prompt = f"""Crie RELATÓRIO EXECUTIVO consolidando toda a inteligência competitiva coletada.
{len(all_analyses)} perfis | @{config.get('my_profile')} | Nicho: {my_niche}{loc} | {datetime.now().strftime('%d/%m/%Y')}

ANÁLISES:
{json.dumps(summaries, ensure_ascii=False, indent=2)}

### PANORAMA COMPETITIVO
Situação atual do mercado no Instagram para o nicho {my_niche}{loc}.

### POSIÇÃO COMPETITIVA ATUAL
Onde você está em relação aos concorrentes.

### 3 PRIORIDADES IMEDIATAS
As 3 ações mais importantes agora.

### OPORTUNIDADES DE MERCADO
O que nenhum concorrente está fazendo bem.

### PLANO 90 DIAS
3 fases de 30 dias com marcos claros.

Seja direto, executivo, máx 700 palavras."""
    msg = ai.messages.create(model="claude-opus-4-6", max_tokens=2000,
                              messages=[{"role": "user", "content": prompt}])
    return msg.content[0].text

def run_analysis_thread(config):
    global run_status
    run_status.update({"running": True, "logs": [], "finished": False,
                       "error": None, "progress": 0})

    apify_token = config.get("apify_token") or os.getenv("APIFY_TOKEN", "")
    anthropic_key = config.get("anthropic_key") or os.getenv("ANTHROPIC_API_KEY", "")

    def log(msg, level="info"):
        run_status["logs"].append({"msg": msg, "level": level,
                                   "time": datetime.now().strftime("%H:%M:%S")})

    try:
        if not apify_token:
            raise Exception("Apify Token não configurado. Vá em Configurações.")
        if not anthropic_key:
            raise Exception("Anthropic API Key não configurada. Vá em Configurações.")

        profiles = [{"username": config["my_profile"], "type": "own"}]
        profiles += [{"username": c, "type": "competitor"} for c in config.get("competitors", [])]
        run_status["total"] = len(profiles)
        all_analyses = []
        my_niche = config.get("niche", "")

        for i, p in enumerate(profiles):
            username = p["username"].lstrip("@")
            label = "MEU PERFIL" if p["type"] == "own" else "CONCORRENTE"
            run_status.update({"current_profile": username, "progress": i})
            log(f"[{label}] Coletando @{username}...", "info")

            try:
                data = scrape_profile(username, apify_token)
            except Exception as e:
                log(f"⚠️  @{username} — {str(e)}", "warn")
                continue

            if not data:
                log(f"⚠️  @{username} — perfil não encontrado ou privado", "warn")
                continue

            followers = data.get("followersCount", 0)
            posts_count = len(data.get("posts", []))
            log(f"✅ @{username} — {followers:,} seguidores · {posts_count} posts", "success")

            log(f"🔍 Detectando nicho de @{username}...", "info")
            try:
                detected_niche = detect_niche(data, anthropic_key)
                log(f"🏷️  Nicho: {detected_niche}", "info")
            except:
                detected_niche = config.get("niche", "criador de conteúdo")

            if p["type"] == "own" and not my_niche:
                my_niche = detected_niche

            log(f"🤖 Analisando @{username} com IA...", "info")
            try:
                if p["type"] == "own":
                    analysis = analyze_own_profile(data, config, anthropic_key, detected_niche)
                else:
                    analysis = analyze_competitor(data, config, anthropic_key, my_niche, detected_niche)
            except Exception as e:
                log(f"⚠️  Erro na análise de @{username}: {str(e)}", "warn")
                continue

            all_analyses.append({
                "type": p["type"], "username": username,
                "full_name": data.get("fullName", username),
                "followers": followers, "posts_analyzed": posts_count,
                "detected_niche": detected_niche, "analysis": analysis,
                "collected_at": datetime.now().isoformat(),
            })
            log(f"✅ @{username} concluído!", "success")
            time.sleep(1)

        if not all_analyses:
            raise Exception("Nenhum perfil analisado. Verifique os usernames e credenciais.")

        log(f"💡 Gerando plano de conteúdo para '{my_niche}'...", "info")
        try:
            content_plan = generate_content_plan(all_analyses, config, anthropic_key, my_niche)
            log("✅ Plano de conteúdo gerado!", "success")
        except Exception as e:
            content_plan = f"Erro: {str(e)}"
            log(f"⚠️  {str(e)}", "warn")

        log("📋 Gerando relatório executivo...", "info")
        try:
            exec_summary = generate_executive_summary(all_analyses, config, anthropic_key, my_niche)
            log("✅ Relatório executivo gerado!", "success")
        except Exception as e:
            exec_summary = f"Erro: {str(e)}"
            log(f"⚠️  {str(e)}", "warn")

        date_str = datetime.now().strftime("%Y%m%d_%H%M")
        report = {
            "id": date_str,
            "run_date": datetime.now().isoformat(),
            "run_date_br": datetime.now().strftime("%d/%m/%Y às %H:%M"),
            "my_niche": my_niche,
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
        log("📊 Acesse a aba Relatórios para ver os resultados.", "success")

    except Exception as e:
        run_status["error"] = str(e)
        log(f"❌ Erro: {str(e)}", "error")
    finally:
        run_status.update({"running": False, "finished": True})

@app.route("/")
def index():
    return render_template("index.html", config=load_config(), reports=get_reports_list())

@app.route("/api/test-anthropic")
def test_anthropic():
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        return jsonify({"ok": False, "error": "ANTHROPIC_API_KEY not set"})
    try:
        import anthropic as ant
        ai = ant.Anthropic(api_key=key)
        msg = ai.messages.create(model="claude-opus-4-6", max_tokens=10,
                                  messages=[{"role": "user", "content": "Say OK"}])
        return jsonify({"ok": True, "response": msg.content[0].text})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/api/test-apify")
def test_apify():
    token = os.getenv("APIFY_TOKEN", "")
    if not token:
        return jsonify({"ok": False, "error": "APIFY_TOKEN not set"})
    try:
        from apify_client import ApifyClient
        client = ApifyClient(token)
        me = client.user("me").get()
        return jsonify({"ok": True, "username": me.get("username"), "plan": me.get("plan", {}).get("id")})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/api/debug-scrape/<username>")
def debug_scrape(username):
    config = load_config()
    token = config.get("apify_token") or os.getenv("APIFY_TOKEN", "")
    if not token:
        return jsonify({"ok": False, "error": "No Apify token"})
    try:
        client = ApifyClient(token)
        # Quick profile scrape
        run = client.actor("apify/instagram-profile-scraper").call(run_input={
            "usernames": [username.lstrip("@")]
        })
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
        if not items:
            return jsonify({"ok": False, "error": "No data returned"})
        profile = items[0]
        # Show all keys and sample of first post
        first_post = profile.get("latestPosts", [{}])[0] if profile.get("latestPosts") else {}
        return jsonify({
            "ok": True,
            "profile_keys": list(profile.keys()),
            "followers": profile.get("followersCount"),
            "posts_count": profile.get("postsCount"),
            "latest_posts_count": len(profile.get("latestPosts", [])),
            "first_post_keys": list(first_post.keys()) if first_post else [],
            "first_post_sample": {
                "likesCount": first_post.get("likesCount"),
                "commentsCount": first_post.get("commentsCount"),
                "videoViewCount": first_post.get("videoViewCount"),
                "type": first_post.get("type"),
                "caption": (first_post.get("caption") or "")[:200],
                "displayUrl": first_post.get("displayUrl", "")[:100],
                "videoUrl": first_post.get("videoUrl", "")[:100],
                "images": first_post.get("images", [])[:2],
                "timestamp": first_post.get("timestamp"),
            }
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

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


@app.route("/api/report/<report_id>/pdf")
def export_pdf(report_id):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, PageBreak, Table, TableStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER
    from io import BytesIO

    path = REPORTS_DIR / f"{report_id}.json"
    if not path.exists():
        return jsonify({"error": "Não encontrado"}), 404

    r = json.loads(path.read_text(encoding="utf-8"))
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm,
        title=f"Relatório IG Intelligence — {r.get('run_date_br','')}",
    )

    # ── Styles ──
    W = colors.HexColor("#f0f8f4")
    BG = colors.HexColor("#060a08")
    AMBER = colors.HexColor("#e8a020")
    GREEN = colors.HexColor("#22c97a")
    DARK = colors.HexColor("#0f1822")
    MID = colors.HexColor("#7aaa94")
    LIGHT = colors.HexColor("#d8ede6")

    styles = getSampleStyleSheet()

    s_cover_title = ParagraphStyle("cover_title",
        fontName="Helvetica-Bold", fontSize=32, textColor=AMBER,
        spaceAfter=8, alignment=TA_CENTER, leading=36)

    s_cover_sub = ParagraphStyle("cover_sub",
        fontName="Helvetica", fontSize=13, textColor=MID,
        spaceAfter=6, alignment=TA_CENTER)

    s_section = ParagraphStyle("section",
        fontName="Helvetica-Bold", fontSize=15, textColor=AMBER,
        spaceBefore=18, spaceAfter=8, leading=18)

    s_profile_tag = ParagraphStyle("profile_tag",
        fontName="Helvetica-Bold", fontSize=11, textColor=GREEN,
        spaceBefore=14, spaceAfter=6)

    s_body = ParagraphStyle("body",
        fontName="Helvetica", fontSize=9.5, textColor=LIGHT,
        spaceAfter=5, leading=14, backColor=DARK,
        leftIndent=8, rightIndent=8)

    s_meta = ParagraphStyle("meta",
        fontName="Helvetica-Oblique", fontSize=9, textColor=MID,
        spaceAfter=4)

    def hr(): return HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#1e3028"), spaceAfter=10, spaceBefore=6)

    def section(title): return [Paragraph(title, s_section), hr()]

    def profile_block(a):
        badge = "MEU PERFIL" if a["type"] == "own" else "CONCORRENTE"
        nicho = a.get("detected_niche", "")
        followers = f"{a.get('followers',0):,}".replace(",",".")
        tag = f"[{badge}] @{a['username']}  ·  {followers} seguidores  ·  {nicho}"
        items = [Paragraph(tag, s_profile_tag)]
        # Split analysis into paragraphs
        for line in (a.get("analysis") or "").split("
"):
            line = line.strip()
            if not line: continue
            safe = line.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
            items.append(Paragraph(safe, s_body))
        items.append(Spacer(1, 8))
        return items

    story = []

    # ── Cover page ──
    story.append(Spacer(1, 3*cm))
    story.append(Paragraph("IG INTELLIGENCE", s_cover_title))
    story.append(Paragraph("Relatório de Inteligência Competitiva", s_cover_sub))
    story.append(Spacer(1, 0.5*cm))
    story.append(Paragraph(f"Gerado em {r.get('run_date_br','')}", s_cover_sub))
    story.append(Paragraph(f"Perfil: @{r.get('config',{}).get('my_profile','')}   ·   Nicho: {r.get('my_niche','')}", s_cover_sub))
    story.append(Spacer(1, 1*cm))

    # Summary table
    analyses = r.get("analyses", [])
    own = next((a for a in analyses if a["type"]=="own"), None)
    comps = [a for a in analyses if a["type"]=="competitor"]
    tdata = [
        ["Perfil", "Tipo", "Seguidores", "Nicho"],
    ]
    for a in analyses:
        tdata.append([
            f"@{a['username']}",
            "Meu Perfil" if a["type"]=="own" else "Concorrente",
            f"{a.get('followers',0):,}".replace(",","."),
            (a.get("detected_niche") or "")[:40],
        ])
    t = Table(tdata, colWidths=[4*cm, 3*cm, 3*cm, 7*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), AMBER),
        ("TEXTCOLOR", (0,0), (-1,0), colors.black),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 9),
        ("BACKGROUND", (0,1), (-1,-1), DARK),
        ("TEXTCOLOR", (0,1), (-1,-1), LIGHT),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [DARK, colors.HexColor("#162420")]),
        ("GRID", (0,0), (-1,-1), 0.4, colors.HexColor("#1e3028")),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
    ]))
    story.append(t)
    story.append(PageBreak())

    # ── Executive Summary ──
    story += section("RELATÓRIO EXECUTIVO")
    for line in (r.get("executive_summary") or "").split("
"):
        line = line.strip()
        if not line: continue
        safe = line.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        story.append(Paragraph(safe, s_body))
    story.append(PageBreak())

    # ── My Profile ──
    if own:
        story += section("ANÁLISE DO MEU PERFIL")
        story += profile_block(own)
        story.append(PageBreak())

    # ── Competitors ──
    if comps:
        story += section("ANÁLISE DOS CONCORRENTES")
        for a in comps:
            story += profile_block(a)
            story.append(hr())
        story.append(PageBreak())

    # ── Content Plan ──
    story += section("PLANO DE CONTEÚDO — 4 SEMANAS")
    for line in (r.get("content_plan") or "").split("
"):
        line = line.strip()
        if not line: continue
        safe = line.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        story.append(Paragraph(safe, s_body))

    doc.build(story)
    buf.seek(0)

    from flask import send_file
    filename = f"IG_Intelligence_{r.get('config',{}).get('my_profile','perfil')}_{report_id}.pdf"
    return send_file(buf, mimetype="application/pdf",
                     as_attachment=True, download_name=filename)

def get_reports_list():
    reports = []
    for f in sorted(REPORTS_DIR.glob("*.json"), reverse=True):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            reports.append({
                "id": d["id"], "run_date_br": d.get("run_date_br", d["id"]),
                "profiles_analyzed": d.get("profiles_analyzed", 0),
                "my_niche": d.get("my_niche", ""),
                "my_profile": d.get("config", {}).get("my_profile", ""),
                "competitors": d.get("config", {}).get("competitors", []),
            })
        except: pass
    return reports

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False)