import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CallbackQueryHandler, CommandHandler, \
    MessageHandler, Filters, CallbackContext
from .access import tg_token

# Import telegram token
TOKEN = tg_token

# PORT = int(os.environ.get('PORT', '8443'))

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO)

logger = logging.getLogger(__name__)


HELP_BUTTON_CALLBACK_DATA = 'help'
help_button = InlineKeyboardButton(
    text='Help',  # text shown to user
    callback_data=HELP_BUTTON_CALLBACK_DATA)  # text sent to bot

EPL_BUTTON_CALLBACK_DATA = 'epl'
epl = InlineKeyboardButton(
    text='🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League',
    callback_data=EPL_BUTTON_CALLBACK_DATA)

LALIGA_BUTTON_CALLBACK_DATA = 'la_liga'
laliga = InlineKeyboardButton(
    text='🇪🇸 La Liga',
    callback_data=LALIGA_BUTTON_CALLBACK_DATA)

SERIEA_BUTTON_CALLBACK_DATA = 'serie_a'
seriea = InlineKeyboardButton(
    text='🇮🇹 Serie A',
    callback_data=SERIEA_BUTTON_CALLBACK_DATA)

BUNDESLIGA_BUTTON_CALLBACK_DATA = 'bundesliga'
bundesliga = InlineKeyboardButton(
    text='🇩🇪 Bundesliga',
    callback_data=BUNDESLIGA_BUTTON_CALLBACK_DATA)

LIGUE1_BUTTON_CALLBACK_DATA = 'ligue_1'
ligue1 = InlineKeyboardButton(
    text='🇫🇷 Ligue 1',
    callback_data=LIGUE1_BUTTON_CALLBACK_DATA)

RPL_BUTTON_CALLBACK_DATA = 'rpl'
rpl = InlineKeyboardButton(
    text='🇷🇺 Russian Premier League',
    callback_data=RPL_BUTTON_CALLBACK_DATA)

league_keyboard = [[epl], [laliga], [seriea], [bundesliga], [ligue1], [rpl]]
league_button_callback_data = [EPL_BUTTON_CALLBACK_DATA,
                               LALIGA_BUTTON_CALLBACK_DATA,
                               SERIEA_BUTTON_CALLBACK_DATA,
                               BUNDESLIGA_BUTTON_CALLBACK_DATA,
                               LIGUE1_BUTTON_CALLBACK_DATA,
                               RPL_BUTTON_CALLBACK_DATA]


# Define a few command handlers. These usually take the two arguments update
# and context. Error handlers also receive the raised TelegramError object
# in error.
def start(update: Update, _: CallbackContext):
    """Send a message when the command /start is issued."""
    reply_markup = InlineKeyboardMarkup(league_keyboard)
    update.message.reply_text('Hi!\nI am GetFootballStats bot.\n'
                              'I can get you updates on '
                              'football player stats '
                              'in a .csv-file.\n'
                              'Choose a league:',
                              reply_markup=reply_markup)
    return CallbackContext


def button(update: Update, _: CallbackContext):
    """Receive league name from buttons and upload .csv file back"""
    today = datetime.today().strftime('%d-%m-%Y')
    chat_id = update.effective_message.chat_id
    query = update.callback_query
    cqd = query.data
    if cqd == HELP_BUTTON_CALLBACK_DATA:
        help_command(update, _)
    elif cqd in league_button_callback_data:
        with open(f'./tmstats/'
                  f'{str(cqd)}/'
                  f'{str(cqd)}_stats_2021.csv', 'rb') as file:
            _.bot.sendDocument(chat_id=chat_id,
                               document=file,
                               filename=f'{str(cqd)}_stats_'
                                        f'{str(today)}.csv')
    query.answer()


def help_command(update: Update, _: CallbackContext) -> None:
    """Send a message when the command /help is issued."""
    update.message.reply_text('Use /start to begin')


def echo(update: Update):
    """Echo the user message."""
    update.message.reply_text(update.message.text)


def error(update: Update, context: CallbackContext):
    """Log Errors caused by Updates."""
    logger.warning('Update "%s" caused error "%s"', update, context.error)


def main():
    """Start the bot."""
    updater = Updater(TOKEN, use_context=True)

    # Get the dispatcher to register handlers
    dp = updater.dispatcher

    # Instantiate the bot
    bot = updater.bot
    print('Your bot is --->', bot.username)

    # for command-answer in telegram
    dp.add_handler(CommandHandler('start', start,
                                  pass_args=True))
    dp.add_handler(CommandHandler('help', help_command,
                                  pass_args=True))
    dp.add_handler(CallbackQueryHandler(button))

    # for non-command i.e message — echo the message on telegram
    dp.add_handler(MessageHandler(Filters.text &
                                  ~Filters.command, echo))

    # log all errors
    dp.add_error_handler(error)

    # start the Bot
    # updater.start_webhook(listen='0.0.0.0',
    #                       port=PORT,
    #                       url_path=TOKEN,
    #                       webhook_url='https://getfootballstats.herokuapp.com/'
    #                                   + TOKEN)

    # Run the bot until you press Ctrl-C or the process receives SIGINT,
    # SIGTERM or SIGABRT. This should be used most of the time, since
    # start_polling() is non-blocking and will stop the bot gracefully.
    updater.start_polling()
    # updater.idle()


if __name__ == '__main__':
    main()
