import logging
import sane
import systemd.daemon
from datetime import datetime
from functools import wraps
from pypass import PasswordStore as PStore
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import filters, ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

token = PStore().get_decrypted_password('token')
users = list(map(int, PStore().get_decrypted_password('users').split()))


def restricted(func):
    @wraps(func)
    async def wrapped(update, context, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in users:
            msg = f"Unauthorized access denied for {user_id}."
            logging.warning(msg)
            return
        return await func(update, context, *args, **kwargs)
    return wrapped


def init_scan():
    sane.exit()
    sane.init()
    devices = sane.get_devices()
    global scanner
    if devices:
        scanner = sane.open(devices[0][0])
    else:
        scanner = {}
    return scanner


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="I'm a bot, please talk to me!")


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Sorry, I didn't understand that command.")


@restricted
async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    # args = " ".join(context.args)
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    try:
        params = scanner.get_parameters()
    except AttributeError as e:
        logging.warning(e)
        init_scan()
        if scanner == {}:
            text = "Can't initialize scanner. Please check device power and connection."
            await context.bot.send_message(chat_id=chat_id, text=text)
            return
        else:
            params = scanner.get_parameters()
    scanner.start()
    params_formatted = f'mode={params[0]}, dimensions={params[2]}, depth={params[3]}'
    scan_msg = await context.bot.send_message(chat_id=chat_id, text=f"Starting scan with params: {params_formatted}")
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
    try:
        im = scanner.snap()
    except Exception as e:
        logging.warning(e)
        text = "Can't connect to scanner. Please check device power and connection."
        await context.bot.send_message(chat_id=chat_id, text=text)
        await context.bot.delete_message(chat_id=chat_id, message_id=scan_msg.message_id)
    else:
        filename = 'scan-' + datetime.now().strftime("%d-%m-%YT%H-%M") + '.png'
        im.save(filename)
        await context.bot.send_document(chat_id=chat_id, document=filename, caption=f'Scan params: {params_formatted}')
        await context.bot.delete_message(chat_id=chat_id, message_id=scan_msg.message_id)


if __name__ == '__main__':
    application = ApplicationBuilder().token(token).build()
    
    start_handler = CommandHandler('start', start)
    application.add_handler(start_handler)

    scan_handler = CommandHandler('scan', scan, block=True)
    application.add_handler(scan_handler)

    unknown_handler = MessageHandler(filters.COMMAND, unknown)
    application.add_handler(unknown_handler)

    scanner = init_scan()
    systemd.daemon.notify('READY=1')
    application.run_polling()
