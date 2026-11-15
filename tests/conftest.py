"""Configuração comum dos testes."""

import os

# Os testes nunca leem o .env da raiz: nada de chave real da OpenAI ou do Twilio.
os.environ["CROP_OPT_LOAD_DOTENV"] = "0"
