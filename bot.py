import os
import json
import logging
import subprocess
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY   = os.getenv("GROQ_API_KEY")
ALLOWED_USER   = int(os.getenv("ALLOWED_USER_ID"))
MODEL          = "llama-3.3-70b-versatile"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)
groq_client = Groq(api_key=GROQ_API_KEY)

def ejecutar_comando(comando):
    try:
        resultado = subprocess.check_output(
            comando, shell=True, stderr=subprocess.STDOUT, timeout=15, text=True)
        return resultado.strip() or "(sin salida)"
    except subprocess.TimeoutExpired:
        return "Timeout: mas de 15 segundos."
    except subprocess.CalledProcessError as e:
        return f"Error ({e.returncode}): {e.output.strip()}"

TOOLS_FN = {
    "ejecutar_comando": ejecutar_comando,
}

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "ejecutar_comando",
            "strict": True,
            "description": "Ejecuta un comando en cmd en Windows 10.",
            "parameters": {
                "type": "object",
                "properties": {
                    "comando": {"type": "string", "description": "Comando a ejecutar"}
                },
                "required": ["comando"],
                "additionalProperties": False
            }
        }
    }
]

SYSTEM_PROMPT = f"""Eres un asistente de terminal corriendo en una PC con windows 10.
Puedes ejecutar comandos.

Cuando necesites usar una herramienta, SIEMPRE usa el formato oficial de function calling.
NUNCA uses formatos como <function=...> o [TOOL: ...].
Los argumentos SIEMPRE deben ser JSON válido.
Las URLs deben ir como strings planos, sin markdown ni underscores adicionales.

Nunca uses comandos destructivos.
Si la solicitud requiere generar codigo solo genera el source y guardalo.
Se conciso"""

def run_agent(user_message):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": user_message}
    ]

    for _ in range(3): # 3 pasos extra en caso de que falle el primer paso
        try:
            response = groq_client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOLS_SCHEMA,
                tool_choice="auto",
                parallel_tool_calls=False,
                max_tokens=512,
            )
        except Exception as e:
            return f"Error al llamar al modelo: {e}"

        msg = response.choices[0].message
        print(f"\n\n\n Eleccion del modelo: \n{msg} \n\n\n")
        
        
        if not msg.tool_calls:
            return msg.content or "(sin respuesta)"

        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ]
        })

        for tc in msg.tool_calls:
            nombre = tc.function.name
            try:
                args = json.loads(tc.function.arguments) or {}
            except (json.JSONDecodeError, TypeError):
                args = {}
            args = {k: v for k, v in args.items() if k}

            log.info(f"Tool: {nombre}({args})")

            if nombre in TOOLS_FN:
                resultado = TOOLS_FN[nombre](**args)
            else:
                resultado = f"Herramienta '{nombre}' no encontrada."

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": resultado
            })

    return "Alcance el limite de pasos. Intenta reformular."

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER:
        await update.message.reply_text("No autorizado.")
        return

    log.info(f"Mensaje: {update.message.text}")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        respuesta = run_agent(update.message.text)
    except Exception as e:
        log.error(f"Error: {e}")
        respuesta = f"Error interno: {e}"

    print(f"\n\n RESULTADO DEL BOT : \n {respuesta} \n\n\n ")
    await update.message.reply_text(respuesta)

async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Bot activo. Puedo ejecutar comandos y revisar el estado de la RPi."
    )

def main():
    log.info("Iniciando bot...")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^/start'), handle_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    log.info("Bot corriendo.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    
    main()
    