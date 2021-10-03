import logging
import telegram
from telegram.ext import Updater, CallbackQueryHandler, CommandHandler, \
    MessageHandler, Filters
import os
from getfootballstats.tmstats.controls import GetData
PORT = int(os.environ.get('PORT', '8443'))

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO)

logger = logging.getLogger(__name__)
TOKEN = '2039746632:AAE3ZoHPIA7_ypptqtOmPctB8WhSzI9OBH8'

HELP_BUTTON_CALLBACK_DATA = 'A unique text for help button callback data'
help_button = telegram.InlineKeyboardButton(
    text='Help',  # text shown to user
    callback_data=HELP_BUTTON_CALLBACK_DATA)  # text sent to bot

EPL_BUTTON_CALLBACK_DATA = 'epl'
epl = telegram.InlineKeyboardButton(
    text='Premier League',
    callback_data=EPL_BUTTON_CALLBACK_DATA)

LALIGA_BUTTON_CALLBACK_DATA = 'la_liga'
laliga = telegram.InlineKeyboardButton(
    text='La Liga',
    callback_data=LALIGA_BUTTON_CALLBACK_DATA)

BUNDESLIGA_BUTTON_CALLBACK_DATA = 'bundesliga'
bundesliga = telegram.InlineKeyboardButton(
    text='Bundesliga',
    callback_data=BUNDESLIGA_BUTTON_CALLBACK_DATA)

LIGUE1_BUTTON_CALLBACK_DATA = 'ligue_1'
ligue1 = telegram.InlineKeyboardButton(
    text='Ligue 1',
    callback_data=LIGUE1_BUTTON_CALLBACK_DATA)

RPL_BUTTON_CALLBACK_DATA = 'rpl'
rpl = telegram.InlineKeyboardButton(
    text='Russian Premier League',
    callback_data=RPL_BUTTON_CALLBACK_DATA)

league_buttons = [epl, laliga, bundesliga, ligue1, rpl]
league_button_callback_data = [EPL_BUTTON_CALLBACK_DATA,
                               LALIGA_BUTTON_CALLBACK_DATA,
                               BUNDESLIGA_BUTTON_CALLBACK_DATA,
                               LIGUE1_BUTTON_CALLBACK_DATA,
                               RPL_BUTTON_CALLBACK_DATA]


# Define a few command handlers. These usually take the two arguments update
# and context. Error handlers also receive the raised TelegramError object
# in error.
def command_handler_start(bot, update):
    """Send a message when the command /start is issued."""
    chat_id = update.message.from_user.id
    bot.send_message(
        chat_id=chat_id,
        text='Hi! I am GetFootballStats bot. I can get you updates on '
             'football statistics, just pick a league and a year! '
             'Press "Help" button proceed.',
        reply_markup=telegram.InlineKeyboardMarkup([[help_button]]))


def command_handler_help(bot, update):
    """Send a message when the command /help is issued."""
    chat_id = update.message.from_user.id
    bot.send_message(
        chat_id=chat_id,
        text='Pick a football league:',
        reply_markup=telegram.InlineKeyboardMarkup([league_buttons]))


def command_handler_league(bot, update, league):
    """Receive league name from buttons and upload .csv file back"""
    GetData(league, '2021').teams()
    chat_id = update.message.from_user.id
    with open(f'{str(league)}/{str(league)}_teams_2021.csv', 'rb') as file:
        bot.send_document(chat_id=chat_id,
                          document=file,
                          filename=f'{str(league)}_teams_2021.csv')


def callback_query_handler(bot, update):
    cqd = update.callback_query.data
    # message_id = update.callback_query.message.message_id
    # update_id = update.update_id
    if cqd == HELP_BUTTON_CALLBACK_DATA:
        command_handler_help(bot, update)
    elif cqd in league_button_callback_data:
        command_handler_league(bot, update, league=cqd)


def echo(update):
    """Echo the user message."""
    update.message.reply_text(update.message.text)


def error(update, context):
    """Log Errors caused by Updates."""
    logger.warning('Update "%s" caused error "%s"', update, context.error)


def main():
    """Start the bot."""
    # Create the GetData and pass it your bot's token.
    # Make sure to set use_context=True to use the new context based callbacks
    # Post version 12 this will no longer be necessary
    updater = Updater(TOKEN, use_context=True)

    # Get the dispatcher to register handlers
    dp = updater.dispatcher

    # Instantiate the bot
    bot = updater.bot
    print('Your bot is --->', bot.username)

    # on different commands - answer in Telegram
    dp.add_handler(CommandHandler('start', command_handler_start))
    dp.add_handler(CommandHandler('help', command_handler_help))
    dp.add_handler(CallbackQueryHandler(callback_query_handler))
    dp.add_handler(CommandHandler('league', command_handler_league))

    # on non-command i.e message - echo the message on Telegram
    dp.add_handler(MessageHandler(Filters.text, echo))

    # log all errors
    dp.add_error_handler(error)

    # Start the Bot
    updater.start_webhook(listen="0.0.0.0",
                          port=int(PORT),
                          url_path=TOKEN)
    updater.bot.setWebhook('https://getfootballstats.herokuapp.com/' + TOKEN)

    # Run the bot until you press Ctrl-C or the process receives SIGINT,
    # SIGTERM or SIGABRT. This should be used most of the time, since
    # start_polling() is non-blocking and will stop the bot gracefully.

    updater.start_polling()
    # updater.idle()


if __name__ == '__main__':
    main()
