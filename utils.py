# utils.py
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus
import re # For cleaning CNPJ

def search_link(nome, assunto):
    try:
        query = f"{nome} {assunto} site:midiajur.com.br"
        encoded_query = quote_plus(query)
        url = f"https://www.google.com/search?q={encoded_query}"
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        for link_tag in soup.find_all('a', href=True):
            href = link_tag['href']
            if 'midiajur.com.br' in href and href.startswith('/url?q='):
                real_link = href.split('&')[0].replace('/url?q=', '')
                return real_link
        
        return 'Link não encontrado'
    except Exception as e:
        print(f"Erro ao buscar link: {e}")
        return 'Erro na busca'

def clean_cnpj(cnpj):
    """Removes punctuation from CNPJ string."""
    return re.sub(r'[^0-9]', '', cnpj)

def fetch_cnpj_data_receitaws(cnpj):
    """
    Fetches company data (name and partners/QSA) from ReceitaWS API.
    """
    cleaned_cnpj = clean_cnpj(cnpj)
    if not cleaned_cnpj or len(cleaned_cnpj) != 14:
        return {'error': 'CNPJ inválido ou não fornecido. Deve conter 14 dígitos.'}

    url = f"https://www.receitaws.com.br/v1/cnpj/{cleaned_cnpj}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Flask App Contact: seu_email@example.com)" 
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code == 429: 
             try:
                 error_data = response.json()
                 return {'error': error_data.get('message', 'Muitas requisições para a API da ReceitaWS. Tente novamente mais tarde.')}
             except ValueError:
                 return {'error': 'Muitas requisições para a API da ReceitaWS. Tente novamente mais tarde (status 429).'}

        response.raise_for_status()
        
        data = response.json()
        
        if data.get('status') == 'ERROR':
            return {'error': data.get('message', 'Erro ao consultar CNPJ na ReceitaWS.')}
            
        company_name = data.get('nome')
        qsa = data.get('qsa', [])
        
        partners_names = [] 
        if qsa:
            for member in qsa:
                if member.get('nome'):
                    partners_names.append(member.get('nome'))
        
        return {
            'nome_empresa': company_name,
            'socios_nomes': partners_names 
        }
        
    except requests.exceptions.HTTPError as e:
        return {'error': f'Erro HTTP {e.response.status_code} ao consultar CNPJ: {str(e)}'}
    except requests.exceptions.RequestException as e:
        print(f"Erro na requisição para ReceitaWS: {e}")
        return {'error': f'Erro de conexão ao consultar CNPJ: {str(e)}'}
    except ValueError: 
        return {'error': 'Erro ao decodificar resposta JSON da API da ReceitaWS.'}