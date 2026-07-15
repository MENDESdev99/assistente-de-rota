import os
import sqlite3
from pathlib import Path
from uuid import uuid4

from flask import Flask, flash, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.utils import secure_filename


APP_NAME = "Assistente de Rota"
ACCESS_PASSWORD = os.environ.get("ACCESS_PASSWORD", "rota2026")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "1234")
SECRET_KEY = os.environ.get("SECRET_KEY", "troque-esta-chave-no-render")

BASE_DIR = Path(__file__).parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
DATABASE = DATA_DIR / "assistente_rota.db"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

TEMPLATE_FOLDER = "templates" if (BASE_DIR / "templates").exists() else "."
STATIC_FOLDER = "static" if (BASE_DIR / "static").exists() else "."

app = Flask(__name__, template_folder=TEMPLATE_FOLDER, static_folder=STATIC_FOLDER)
app.secret_key = SECRET_KEY


def preparar_pastas():
    DATA_DIR.mkdir(exist_ok=True)
    UPLOAD_DIR.mkdir(exist_ok=True)


def conectar_banco():
    conexao = sqlite3.connect(DATABASE)
    conexao.row_factory = sqlite3.Row
    return conexao


def criar_banco():
    preparar_pastas()

    with conectar_banco() as conexao:
        conexao.execute(
            """
            CREATE TABLE IF NOT EXISTS cadastros (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                matricula TEXT NOT NULL,
                dica TEXT NOT NULL,
                localizacao TEXT NOT NULL,
                foto TEXT,
                criado_em DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def usuario_logado():
    return session.get("logado") is True


def extensao_permitida(nome_arquivo):
    if "." not in nome_arquivo:
        return False

    extensao = nome_arquivo.rsplit(".", 1)[1].lower()
    return extensao in ALLOWED_EXTENSIONS


def salvar_foto(arquivo):
    if not arquivo or arquivo.filename == "":
        return ""

    if not extensao_permitida(arquivo.filename):
        flash("A foto precisa ser PNG, JPG, JPEG, GIF ou WEBP.")
        return ""

    nome_original = secure_filename(arquivo.filename)
    extensao = nome_original.rsplit(".", 1)[1].lower()
    nome_final = f"{uuid4().hex}.{extensao}"
    caminho_final = UPLOAD_DIR / nome_final
    arquivo.save(caminho_final)
    return nome_final


@app.before_request
def garantir_banco():
    criar_banco()


@app.route("/", methods=["GET", "POST"])
def login():
    if usuario_logado():
        return redirect(url_for("cadastros"))

    if request.method == "POST":
        senha = request.form.get("senha", "")

        if senha == ACCESS_PASSWORD:
            session["logado"] = True
            return redirect(url_for("cadastros"))

        flash("Senha incorreta.")

    return render_template("login.html", app_name=APP_NAME)


@app.route("/cadastros")
def cadastros():
    if not usuario_logado():
        return redirect(url_for("login"))

    busca = request.args.get("busca", "").strip()

    with conectar_banco() as conexao:
        if busca:
            termo = f"%{busca}%"
            registros = conexao.execute(
                """
                SELECT * FROM cadastros
                WHERE matricula LIKE ? OR dica LIKE ? OR localizacao LIKE ?
                ORDER BY id DESC
                """,
                (termo, termo, termo),
            ).fetchall()
        else:
            registros = conexao.execute("SELECT * FROM cadastros ORDER BY id DESC").fetchall()

    return render_template("cadastros.html", app_name=APP_NAME, registros=registros, busca=busca)


@app.route("/adicionar", methods=["POST"])
def adicionar():
    if not usuario_logado():
        return redirect(url_for("login"))

    matricula = request.form.get("matricula", "").strip()
    dica = request.form.get("dica", "").strip()
    localizacao = request.form.get("localizacao", "").strip()
    foto = request.files.get("foto")

    if not matricula or not dica or not localizacao:
        flash("Preencha matricula, dica e localizacao.")
        return redirect(url_for("cadastros"))

    nome_foto = salvar_foto(foto)

    with conectar_banco() as conexao:
        conexao.execute(
            """
            INSERT INTO cadastros (matricula, dica, localizacao, foto)
            VALUES (?, ?, ?, ?)
            """,
            (matricula, dica, localizacao, nome_foto),
        )

    flash("Cadastro adicionado com sucesso.")
    return redirect(url_for("cadastros"))


@app.route("/apagar/<int:cadastro_id>", methods=["POST"])
def apagar(cadastro_id):
    if not usuario_logado():
        return redirect(url_for("login"))

    senha_admin = request.form.get("senha_admin", "")

    if senha_admin != ADMIN_PASSWORD:
        flash("Senha do dono incorreta.")
        return redirect(url_for("cadastros"))

    with conectar_banco() as conexao:
        cadastro = conexao.execute("SELECT foto FROM cadastros WHERE id = ?", (cadastro_id,)).fetchone()
        conexao.execute("DELETE FROM cadastros WHERE id = ?", (cadastro_id,))

    if cadastro and cadastro["foto"]:
        caminho_foto = UPLOAD_DIR / cadastro["foto"]
        if caminho_foto.exists():
            caminho_foto.unlink()

    flash("Cadastro apagado.")
    return redirect(url_for("cadastros"))


@app.route("/uploads/<path:nome_arquivo>")
def uploads(nome_arquivo):
    if not usuario_logado():
        return redirect(url_for("login"))

    return send_from_directory(UPLOAD_DIR, nome_arquivo)


@app.route("/sair", methods=["POST"])
def sair():
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    criar_banco()
    app.run(host="0.0.0.0", port=5000, debug=True)
