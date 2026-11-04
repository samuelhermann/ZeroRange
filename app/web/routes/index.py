"""Root index — lists every registered scenario with its live progress."""

from flask import Blueprint, current_app, render_template_string

from app.core.paths import REPO_ROOT
from app.web.scenario_blueprint import read_progress

index_bp = Blueprint("index", __name__)

_STATIC = REPO_ROOT / "app" / "web" / "static" / "scenarios"

_INDEX_TMPL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ZeroRange</title>
<style>
  :root{--bg:#0e0e0e;--fg:#f4f1ec;--accent:#ff6a00;--dim:#888;--green:#39d353}
  body{background:var(--bg);color:var(--fg);font-family:monospace;padding:2rem;margin:0}
  h1{color:var(--accent);letter-spacing:.1em}
  .scenarios{display:flex;flex-wrap:wrap;gap:1.5rem;margin-top:2rem}
  .card{border:1px solid var(--accent);border-radius:6px;padding:1.5rem;width:200px;
        text-decoration:none;color:var(--fg);transition:background .2s}
  .card:hover{background:#1a1a1a}
  .card img,.card .ph{display:block;margin:0 auto 1rem;width:64px;height:64px}
  .card .ph{border:1px dashed var(--dim);border-radius:50%}
  .card h2{font-size:1rem;text-align:center;margin:0}
  .card p{font-size:.75rem;color:var(--dim);text-align:center;margin:.5rem 0 0}
  .card .done{color:var(--green)}
</style>
</head>
<body>
<h1>ZeroRange</h1>
<p>{% if player %}Now playing: <b>{{ player }}</b> · {% endif %}Select a training scenario
   · <a href="/dashboard/" style="color:var(--accent)">trainer dashboard</a></p>
<div class="scenarios">
{% for sc in scenarios %}
  <a class="card" href="/scenarios/{{ sc.key }}/">
    {% if sc.logo %}<img src="/scenarios/{{ sc.key }}/static/scenarios/{{ sc.key }}/logo.svg" alt="">
    {% else %}<span class="ph"></span>{% endif %}
    <h2>{{ sc.title }}</h2>
    <p class="{{ 'done' if sc.score == sc.max_points else '' }}">{{ sc.score }}/{{ sc.max_points }} pts</p>
  </a>
{% else %}
  <p>No scenario found in challenges/.</p>
{% endfor %}
</div>
</body>
</html>"""


@index_bp.route("/")
def index():
    cards = []
    for scenario in current_app.config["ZR_REGISTRY"]:
        info = read_progress(scenario, current_app.config.get("ZR_DB_PATH"))
        info["logo"] = (_STATIC / scenario.key / "logo.svg").is_file()
        cards.append(info)
    player = cards[0]["player"] if cards else None
    return render_template_string(_INDEX_TMPL, scenarios=cards, player=player)
