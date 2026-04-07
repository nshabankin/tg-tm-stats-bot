import logging
import re
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (CallbackContext, CallbackQueryHandler,
                          CommandHandler, Filters, MessageHandler, Updater)

from config import BASE_DIR, get_bot_token

# PORT = int(os.environ.get('PORT', '8443'))

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO)

logger = logging.getLogger(__name__)
TMSTATS_DIR = BASE_DIR / 'tmstats'
BACK_TO_LEAGUES_CALLBACK_DATA = 'back_to_leagues'
FILE_TYPES = {
    'table': {
        'label': 'League Table',
        'suffix': 'table',
    },
    'stats': {
        'label': 'Player Stats',
        'suffix': 'stats',
    },
}
FORMAT_TYPES = {
    'csv': {
        'label': 'CSV',
        'extension': 'csv',
    },
    'pdf': {
        'label': 'PDF',
        'extension': 'pdf',
    },
}


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


def build_file_options_keyboard(league: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('League Table (CSV)',
                              callback_data=f'file:{league}:table:csv'),
         InlineKeyboardButton('League Table (PDF)',
                              callback_data=f'file:{league}:table:pdf')],
        [InlineKeyboardButton('Player Stats (CSV)',
                              callback_data=f'file:{league}:stats:csv'),
         InlineKeyboardButton('Player Stats (PDF)',
                              callback_data=f'file:{league}:stats:pdf')],
        [InlineKeyboardButton('Back', callback_data=BACK_TO_LEAGUES_CALLBACK_DATA)],
    ])


def get_latest_snapshot_file(league: str, file_type: str,
                             file_format: str) -> Path:
    """Return the latest saved snapshot for the requested league and format."""
    league_dir = TMSTATS_DIR / league
    suffix = FILE_TYPES[file_type]['suffix']
    extension = FORMAT_TYPES[file_format]['extension']
    snapshot_files = sorted(
        league_dir.glob(f'{league}_{suffix}_*.{extension}'),
        key=lambda path: (extract_snapshot_year(path.name), path.stat().st_mtime),
        reverse=True,
    )

    if not snapshot_files:
        raise FileNotFoundError(
            f'No {file_type} {file_format} snapshots found for {league}'
        )

    return snapshot_files[0]


def extract_snapshot_year(filename: str) -> int:
    match = re.search(
        r'_(stats|table|players)_(\d{4})\.(csv|pdf)$',
        filename
    )
    if not match:
        return 0
    return int(match.group(2))


def get_reply_target(update: Update):
    return update.effective_message or update.callback_query.message


# Define a few command handlers. These usually take the two arguments update
# and context. Error handlers also receive the raised TelegramError object
# in error.
def start(update: Update, _: CallbackContext):
    """Send a message when the command /start is issued."""
    reply_markup = InlineKeyboardMarkup(league_keyboard)
    get_reply_target(update).reply_text(
        'Hi!\nI am GetFootballStats bot.\n'
        'I can send you the latest local league table '
        '(with recent form) or player stats snapshot '
        'in CSV or PDF format.\n'
        'Choose a league:',
        reply_markup=reply_markup)


def button(update: Update, context: CallbackContext):
    """Receive league name from buttons and upload .csv file back"""
    query = update.callback_query
    query.answer()
    cqd = query.data
    if cqd == HELP_BUTTON_CALLBACK_DATA:
        help_command(update, context)
    elif cqd == BACK_TO_LEAGUES_CALLBACK_DATA:
        start(update, context)
    elif cqd in league_button_callback_data:
        query.message.reply_text(
            'Choose which snapshot and format you want to download:',
            reply_markup=build_file_options_keyboard(cqd),
        )
    elif cqd.startswith('file:'):
        _, league, file_type, file_format = cqd.split(':', 3)
        try:
            latest_snapshot = get_latest_snapshot_file(league,
                                                       file_type,
                                                       file_format)
        except FileNotFoundError:
            query.message.reply_text(
                'No local snapshot is available for that option yet. '
                'Refresh the league data first.'
            )
            return

        query.message.reply_text(
            f'Sending the latest {FILE_TYPES[file_type]["label"].lower()} '
            f'{FORMAT_TYPES[file_format]["label"]} snapshot: '
            f'{latest_snapshot.name}'
        )
        with latest_snapshot.open('rb') as file:
            context.bot.send_document(chat_id=query.message.chat_id,
                                      document=file,
                                      filename=latest_snapshot.name)


def help_command(update: Update, _: CallbackContext) -> None:
    """Send a message when the command /help is issued."""
    get_reply_target(update).reply_text(
        'Use /start to choose a league, then pick league table '
        'or player stats in CSV or PDF format.')


def echo(update: Update, _: CallbackContext):
    """Echo the user message."""
    update.message.reply_text(update.message.text)


def error(update: Update, context: CallbackContext):
    """Log Errors caused by Updates."""
    logger.warning('Update "%s" caused error "%s"', update, context.error)


def main():
    """Start the bot."""
    updater = Updater(get_bot_token(), use_context=True)

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
    updater.idle()


if __name__ == '__main__':
    main()
