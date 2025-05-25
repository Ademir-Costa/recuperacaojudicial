from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3
from utils import search_link, fetch_cnpj_data_receitaws
import os

app = Flask(__name__)
app.secret_key = 'sua_chave_secreta_aqui'

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(BASE_DIR, 'database')
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, 'recuperacao_judicial.db')

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS grupos (
                id TEXT PRIMARY KEY,
                nome TEXT NOT NULL
            )
        ''')
        
        # Adicionado UNIQUE constraint para (grupo_id, nome, cpf_socio)
        # para facilitar a lógica de "INSERT OR IGNORE" ou checagem.
        # Lidar com NULL em UNIQUE constraint: No SQLite, NULLs não são considerados iguais.
        # Para uma unicidade mais forte, considere tornar cpf_socio NOT NULL ou usar um placeholder.
        # Por simplicidade, a checagem será feita na lógica da aplicação.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS socios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                cpf_socio TEXT,
                grupo_id TEXT NOT NULL,
                link TEXT,
                FOREIGN KEY (grupo_id) REFERENCES grupos (id) ON DELETE CASCADE
            )
        ''')
        # Opcional: Criar um índice para otimizar a checagem de sócio existente
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_socio_lookup ON socios (grupo_id, nome, cpf_socio);
        ''')
        
        conn.commit()
    except Exception as e:
        print(f"Erro ao inicializar banco de dados: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

def get_data_for_table(termo=''):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if termo:
            query = '''
                SELECT s.id, s.nome, s.cpf_socio, g.nome AS grupo_nome, s.link, s.grupo_id
                FROM socios s
                JOIN grupos g ON s.grupo_id = g.id
                WHERE s.nome LIKE ? OR g.nome LIKE ? OR s.grupo_id LIKE ? OR s.cpf_socio LIKE ?
                ORDER BY g.nome, s.nome
            '''
            like_termo = f'%{termo}%'
            cursor.execute(query, (like_termo, like_termo, like_termo, like_termo))
        else:
            query = '''
                SELECT s.id, s.nome, s.cpf_socio, g.nome AS grupo_nome, s.link, s.grupo_id
                FROM socios s
                JOIN grupos g ON s.grupo_id = g.id
                ORDER BY g.nome, s.nome
            '''
            cursor.execute(query)
        
        dados_rows = cursor.fetchall()
        dados = [dict(row) for row in dados_rows]
    except sqlite3.Error as e:
        print(f"Erro ao consultar dados no banco: {e}")
        dados = []
    finally:
        if conn:
            conn.close()
    return dados

@app.route('/', methods=['GET', 'POST'])
def index():
    termo_pesquisa = request.args.get('termo', '').strip()
    
    form_data = {
        'grupo_id': '',
        'grupo_nome': '',
        'socios': [{'nome': '', 'cpf_socio': ''}] 
    }

    if request.method == 'POST':
        form_data['grupo_id'] = request.form.get('grupo_id', '').strip()
        form_data['grupo_nome'] = request.form.get('grupo', '').strip()
        
        nomes_socios_form = request.form.getlist('socio_nome')
        cpfs_socios_form = request.form.getlist('socio_cpf')

        socios_submetidos = []
        for i in range(len(nomes_socios_form)):
            nome = nomes_socios_form[i].strip()
            cpf = cpfs_socios_form[i].strip() if i < len(cpfs_socios_form) else ""
            if nome or cpf: 
                socios_submetidos.append({'nome': nome, 'cpf_socio': cpf})
        
        form_data['socios'] = socios_submetidos if socios_submetidos else [{'nome': '', 'cpf_socio': ''}]

        final_grupo_nome = form_data['grupo_nome']
        # final_socios_info agora são os sócios que o usuário quer *garantir* que estejam no grupo (adicionar se não estiverem)
        socios_para_processar = list(form_data['socios']) 

        if form_data['grupo_id']:
            api_data = fetch_cnpj_data_receitaws(form_data['grupo_id'])
            if api_data: # Processa dados da API se disponíveis
                if 'error' in api_data:
                    flash(f"Aviso (ReceitaWS): {api_data['error']}", 'warning')
                elif 'warning' in api_data:
                    flash(f"Aviso (ReceitaWS): {api_data['warning']}", 'warning')

                if 'nome_empresa' in api_data and api_data['nome_empresa']:
                    final_grupo_nome = api_data['nome_empresa'] # Atualiza nome do grupo se veio da API
                    form_data['grupo_nome'] = final_grupo_nome 

                # Se API retornou sócios, eles são adicionados à lista para processamento
                # A lógica aqui é que o usuário pode ter digitado alguns sócios E a API pode trazer outros.
                # Todos os sócios (do form + da API que não estão já no form por nome) serão tentados adicionar.
                if 'socios_nomes' in api_data and api_data['socios_nomes']:
                    nomes_socios_api = api_data['socios_nomes']
                    nomes_ja_no_form_upper = {s['nome'].upper() for s in socios_para_processar if s['nome']}
                    
                    novos_socios_da_api_para_adicionar = []
                    for nome_api in nomes_socios_api:
                        if nome_api.upper() not in nomes_ja_no_form_upper:
                            novos_socios_da_api_para_adicionar.append({'nome': nome_api, 'cpf_socio': ''}) # CPF em branco
                    
                    if novos_socios_da_api_para_adicionar:
                        socios_para_processar.extend(novos_socios_da_api_para_adicionar)
                        flash(f'{len(novos_socios_da_api_para_adicionar)} Sócio(s) adicional(is) sugerido(s) pela Receita Federal. Verifique/Preencha os CPFs e salve.', 'info')
                
                form_data['socios'] = socios_para_processar if socios_para_processar else [{'nome':'', 'cpf_socio':''}]
        
        validation_error = False
        if not form_data['grupo_id']:
            flash('CPF/CNPJ do Grupo é obrigatório!', 'error')
            validation_error = True
        if not final_grupo_nome: 
            flash('Nome do Grupo é obrigatório!', 'error')
            validation_error = True
        
        # Valida se há pelo menos um sócio com nome na lista final a ser processada
        if not any(s.get('nome','').strip() for s in socios_para_processar if isinstance(s, dict)):
            flash('Ao menos um Sócio com nome preenchido é obrigatório na lista a ser salva!', 'error')
            validation_error = True
            if not form_data['socios'] or not (isinstance(form_data['socios'][0], dict) and form_data['socios'][0].get('nome')):
                 form_data['socios'] = [{'nome': '', 'cpf_socio': ''}]

        if not validation_error:
            conn = None
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                
                # Atualiza ou insere o grupo
                cursor.execute(
                    'INSERT OR REPLACE INTO grupos (id, nome) VALUES (?, ?)',
                    (form_data['grupo_id'], final_grupo_nome)
                )
                
                # MODIFICAÇÃO PRINCIPAL: Não deleta mais os sócios existentes.
                # Apenas adiciona os sócios listados no formulário que ainda não existem no grupo.
                socios_adicionados_count = 0
                socios_existentes_count = 0

                for socio_data in socios_para_processar:
                    if isinstance(socio_data, dict) and socio_data.get('nome','').strip(): 
                        nome_socio = socio_data['nome'].strip()
                        # Trata CPF vazio como None para consistência com o banco
                        cpf_socio_val = socio_data.get('cpf_socio','').strip()
                        cpf_socio_db = cpf_socio_val if cpf_socio_val else None 

                        # Verifica se o sócio (combinação de nome e CPF) já existe no grupo
                        # A checagem de CPF precisa ser cuidadosa com NULLs
                        if cpf_socio_db:
                            cursor.execute(
                                "SELECT id FROM socios WHERE grupo_id = ? AND nome = ? AND cpf_socio = ?",
                                (form_data['grupo_id'], nome_socio, cpf_socio_db)
                            )
                        else: # CPF não informado, verifica só por nome e CPF IS NULL
                             cursor.execute(
                                "SELECT id FROM socios WHERE grupo_id = ? AND nome = ? AND cpf_socio IS NULL",
                                (form_data['grupo_id'], nome_socio)
                            )
                        existing_socio = cursor.fetchone()

                        if not existing_socio:
                            link = search_link(nome_socio, 'recuperação judicial')
                            cursor.execute(
                                'INSERT INTO socios (nome, cpf_socio, grupo_id, link) VALUES (?, ?, ?, ?)',
                                (nome_socio, cpf_socio_db, form_data['grupo_id'], link)
                            )
                            socios_adicionados_count += 1
                        else:
                            socios_existentes_count +=1
                
                conn.commit()

                if socios_adicionados_count > 0:
                    flash(f'{socios_adicionados_count} sócio(s) novo(s) adicionado(s) ao grupo "{final_grupo_nome}".', 'success')
                if socios_existentes_count > 0:
                    flash(f'{socios_existentes_count} sócio(s) listado(s) já existia(m) no grupo e foram mantidos/ignorados.', 'info')
                if socios_adicionados_count == 0 and socios_existentes_count == 0 and any(s.get('nome','').strip() for s in socios_para_processar if isinstance(s, dict)):
                    flash('Nenhum novo sócio para adicionar ou todos os listados já existem.', 'info')
                elif not any(s.get('nome','').strip() for s in socios_para_processar if isinstance(s, dict)):
                     flash('Nenhum sócio informado para adicionar ao grupo.', 'warning')


                return redirect(url_for('index', termo=termo_pesquisa)) 
            except sqlite3.Error as e:
                if conn: conn.rollback()
                flash(f'Erro ao salvar dados no banco: {str(e)}', 'error')
            finally:
                if conn: conn.close()

        dados_para_tabela = get_data_for_table(termo_pesquisa)
        return render_template('index.html', 
                               dados=dados_para_tabela, 
                               termo=termo_pesquisa,
                               submitted_grupo_id=form_data['grupo_id'],
                               submitted_grupo_nome=final_grupo_nome, 
                               submitted_socios=form_data['socios'])

    # Método GET
    dados_para_tabela = get_data_for_table(termo_pesquisa)
    initial_socios_data = form_data['socios']
    if not initial_socios_data or not (isinstance(initial_socios_data[0], dict) and (initial_socios_data[0].get('nome') or initial_socios_data[0].get('cpf_socio')) ):
        initial_socios_data = [{'nome':'', 'cpf_socio':''}]

    return render_template('index.html', 
                           dados=dados_para_tabela, 
                           termo=termo_pesquisa,
                           submitted_grupo_id=form_data['grupo_id'],
                           submitted_grupo_nome=form_data['grupo_nome'],
                           submitted_socios=initial_socios_data)


@app.route('/excluir/<int:id>', methods=['POST'])
def excluir_socio(id):
    conn = None
    termo_pesquisa_atual = request.form.get('termo_pesquisa_hidden_on_delete', '') 
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM socios WHERE id = ?', (id,))
        conn.commit()
        flash('Sócio excluído com sucesso!', 'success')
    except sqlite3.Error as e:
        if conn: conn.rollback()
        flash(f'Erro ao excluir sócio: {str(e)}', 'error')
    finally:
        if conn: conn.close()
    
    return redirect(url_for('index', termo=termo_pesquisa_atual))

if __name__ == '__main__':
    init_db()
    print(f"Banco de dados configurado em: {DB_PATH}")
    app.run(debug=True)