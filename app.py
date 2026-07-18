import os
import sqlite3
from pathlib import Path
from uuid import uuid4

from flask import Flask, flash, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.utils import secure_filename

try:
    import cloudinary
    import cloudinary.uploader
except ImportError:
    cloudinary = None

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None
    dict_row = None


APP_NAME = "Assistente de Rota"
ACCESS_PASSWORD = os.environ.get("ACCESS_PASSWORD", "rota2026")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "1234")
SECRET_KEY = os.environ.get("SECRET_KEY", "troque-esta-chave-no-render")
MAX_FOTOS = 3

BASE_DIR = Path(__file__).parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
DATABASE = DATA_DIR / "assistente_rota.db"
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USANDO_POSTGRES = bool(DATABASE_URL)
CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME", "").strip()
CLOUDINARY_API_KEY = os.environ.get("CLOUDINARY_API_KEY", "").strip()
CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET", "").strip()
USANDO_CLOUDINARY = bool(CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET)
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

TEMPLATE_FOLDER = "templates" if (BASE_DIR / "templates").exists() else "."
STATIC_FOLDER = "static" if (BASE_DIR / "static").exists() else "."

app = Flask(__name__, template_folder=TEMPLATE_FOLDER, static_folder=STATIC_FOLDER)
app.secret_key = SECRET_KEY

if USANDO_CLOUDINARY and cloudinary is not None:
    cloudinary.config(
        cloud_name=CLOUDINARY_CLOUD_NAME,
        api_key=CLOUDINARY_API_KEY,
        api_secret=CLOUDINARY_API_SECRET,
        secure=True,
    )


def preparar_pastas():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def conectar_banco():
    if USANDO_POSTGRES:
        if psycopg is None:
            raise RuntimeError("Instale psycopg para usar DATABASE_URL com Postgres.")

        return psycopg.connect(DATABASE_URL, row_factory=dict_row)

    conexao = sqlite3.connect(DATABASE)
    conexao.row_factory = sqlite3.Row
    return conexao


def executar(conexao, sql, parametros=()):
    if USANDO_POSTGRES:
        sql = sql.replace("?", "%s")

    return conexao.execute(sql, parametros)


def criar_banco():
    preparar_pastas()

    with conectar_banco() as conexao:
        if USANDO_POSTGRES:
            conexao.execute(
                """
                CREATE TABLE IF NOT EXISTS cadastros (
                    id SERIAL PRIMARY KEY,
                    matricula TEXT NOT NULL,
                    endereco TEXT,
                    dica TEXT NOT NULL,
                    localizacao TEXT NOT NULL DEFAULT '',
                    foto TEXT,
                    foto2 TEXT,
                    foto3 TEXT,
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        else:
            conexao.execute(
                """
                CREATE TABLE IF NOT EXISTS cadastros (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    matricula TEXT NOT NULL,
                    endereco TEXT,
                    dica TEXT NOT NULL,
                    localizacao TEXT NOT NULL,
                    foto TEXT,
                    foto2 TEXT,
                    foto3 TEXT,
                    criado_em DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

        migrar_banco(conexao)


def migrar_banco(conexao):
    novas_colunas = {
        "endereco": "TEXT",
        "foto2": "TEXT",
        "foto3": "TEXT",
    }

    if USANDO_POSTGRES:
        for nome, tipo in novas_colunas.items():
            conexao.execute(f"ALTER TABLE cadastros ADD COLUMN IF NOT EXISTS {nome} {tipo}")
        return

    colunas = [linha["name"] for linha in conexao.execute("PRAGMA table_info(cadastros)").fetchall()]

    for nome, tipo in novas_colunas.items():
        if nome not in colunas:
            conexao.execute(f"ALTER TABLE cadastros ADD COLUMN {nome} {tipo}")


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

    if USANDO_CLOUDINARY:
        if cloudinary is None:
            raise RuntimeError("Instale cloudinary para salvar fotos fora do Render.")

        resultado = cloudinary.uploader.upload(
            arquivo,
            folder="assistente-de-rota",
            resource_type="image",
        )
        return resultado.get("secure_url", "")

    nome_original = secure_filename(arquivo.filename)
    extensao = nome_original.rsplit(".", 1)[1].lower()
    nome_final = f"{uuid4().hex}.{extensao}"
    caminho_final = UPLOAD_DIR / nome_final
    arquivo.save(caminho_final)
    return nome_final


def salvar_fotos(arquivos):
    fotos_salvas = []

    for arquivo in arquivos[:MAX_FOTOS]:
        nome_foto = salvar_foto(arquivo)

        if nome_foto:
            fotos_salvas.append(nome_foto)

    while len(fotos_salvas) < MAX_FOTOS:
        fotos_salvas.append("")

    return fotos_salvas


def apagar_fotos(cadastro):
    if USANDO_CLOUDINARY:
        return

    for campo in ("foto", "foto2", "foto3"):
        nome_foto = cadastro[campo] if campo in cadastro.keys() else ""

        if nome_foto:
            caminho_foto = UPLOAD_DIR / nome_foto
            if caminho_foto.exists():
                caminho_foto.unlink()


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
            if USANDO_POSTGRES:
                registros = executar(
                    conexao,
                    """
                    SELECT * FROM cadastros
                    WHERE matricula ILIKE ? OR endereco ILIKE ? OR dica ILIKE ? OR localizacao ILIKE ?
                    ORDER BY id DESC
                    """,
                    (termo, termo, termo, termo),
                ).fetchall()
            else:
                registros = executar(
                    conexao,
                    """
                    SELECT * FROM cadastros
                    WHERE matricula LIKE ? OR endereco LIKE ? OR dica LIKE ? OR localizacao LIKE ?
                    ORDER BY id DESC
                    """,
                    (termo, termo, termo, termo),
                ).fetchall()
        else:
            registros = executar(conexao, "SELECT * FROM cadastros ORDER BY id DESC").fetchall()

    return render_template("cadastros.html", app_name=APP_NAME, registros=registros, busca=busca)


@app.route("/adicionar", methods=["POST"])
def adicionar():
    if not usuario_logado():
        return redirect(url_for("login"))

    matricula = request.form.get("matricula", "").strip()
    endereco = request.form.get("endereco", "").strip()
    dica = request.form.get("dica", "").strip()
    localizacao = request.form.get("localizacao", "").strip()
    fotos = request.files.getlist("fotos")

    if not matricula or not endereco or not dica:
        flash("Preencha matricula, endereco e dica.")
        return redirect(url_for("cadastros"))

    foto1, foto2, foto3 = salvar_fotos(fotos)

    with conectar_banco() as conexao:
        executar(
            conexao,
            """
            INSERT INTO cadastros (matricula, endereco, dica, localizacao, foto, foto2, foto3)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (matricula, endereco, dica, localizacao, foto1, foto2, foto3),
        )

    flash("Cadastro adicionado com sucesso.")
    return redirect(url_for("cadastros"))


@app.route("/editar/<int:cadastro_id>", methods=["POST"])
def editar(cadastro_id):
    if not usuario_logado():
        return redirect(url_for("login"))

    matricula = request.form.get("matricula", "").strip()
    endereco = request.form.get("endereco", "").strip()
    dica = request.form.get("dica", "").strip()
    localizacao = request.form.get("localizacao", "").strip()
    fotos = request.files.getlist("fotos")
    tem_foto_nova = any(arquivo and arquivo.filename for arquivo in fotos)

    if not matricula or not endereco or not dica:
        flash("Preencha matricula, endereco e dica.")
        return redirect(url_for("cadastros"))

    with conectar_banco() as conexao:
        cadastro = executar(conexao, "SELECT * FROM cadastros WHERE id = ?", (cadastro_id,)).fetchone()

        if not cadastro:
            flash("Cadastro nao encontrado.")
            return redirect(url_for("cadastros"))

        if tem_foto_nova:
            apagar_fotos(cadastro)
            foto1, foto2, foto3 = salvar_fotos(fotos)
        else:
            foto1 = cadastro["foto"] or ""
            foto2 = cadastro["foto2"] or ""
            foto3 = cadastro["foto3"] or ""

        executar(
            conexao,
            """
            UPDATE cadastros
            SET matricula = ?, endereco = ?, dica = ?, localizacao = ?, foto = ?, foto2 = ?, foto3 = ?
            WHERE id = ?
            """,
            (matricula, endereco, dica, localizacao, foto1, foto2, foto3, cadastro_id),
        )

    flash("Cadastro atualizado.")
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
        cadastro = executar(conexao, "SELECT * FROM cadastros WHERE id = ?", (cadastro_id,)).fetchone()
        executar(conexao, "DELETE FROM cadastros WHERE id = ?", (cadastro_id,))

    if cadastro:
        apagar_fotos(cadastro)

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
