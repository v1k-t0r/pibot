import logging
import pyudev
import sane
import systemd.daemon
from datetime import datetime
from functools import wraps
from pypass import PasswordStore as PStore
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import filters, ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)

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


def init_scan() -> sane or None:
    sane.exit()
    sane.init()
    devices = sane.get_devices()
    global scanner
    if devices:
        scanner = sane.open(devices[0][0])
        logging.info(scanner)
    else:
        scanner = None
        logging.info("Can't initialize scanner")
    return scanner


def log_event(action, device):
    if 'libsane_matched' and 'ID_MODEL' in device:
        msg = f"{action} {device.get('ID_MODEL')}"
        logging.info(msg)
        init_scan()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a message with three inline buttons attached."""
    keyboard = [
        [
            InlineKeyboardButton("Color scan", callback_data="1"),
            InlineKeyboardButton("B/W scan", callback_data="2"),
        ],
        [InlineKeyboardButton("Multi page scan", callback_data="3")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Scan mode:", reply_markup=reply_markup)


def scan_params(query) -> tuple:
    if not scanner:
        return ()
    if query.data == '2':
        scanner.mode = 'gray'
    else:
        scanner.mode = 'color'
    params = scanner.get_parameters()
    return params


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Sorry, I didn't understand that command.")


@restricted
async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    query = update.callback_query
    await query.answer()
    # args = " ".join(context.args)
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    params = scan_params(query)
    if params == ():
        text = "Can't initialize scanner. Please check device power and connection."
        await context.bot.send_message(chat_id=chat_id, text=text)
        return
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

    application.add_handler(CallbackQueryHandler(scan, block=True))

    unknown_handler = MessageHandler(filters.COMMAND, unknown)
    application.add_handler(unknown_handler)

    scanner = init_scan()
    cont = pyudev.Context()
    monitor = pyudev.Monitor.from_netlink(cont)
    monitor.filter_by('usb')
    observer = pyudev.MonitorObserver(monitor, log_event)
    observer.start()

    systemd.daemon.notify('READY=1')
    application.run_polling()
