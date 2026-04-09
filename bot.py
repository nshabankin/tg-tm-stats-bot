import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (CallbackContext, CallbackQueryHandler,
                          CommandHandler, Filters, MessageHandler, Updater)

from config import get_bot_token
from tmstats.catalog import LEAGUES, LEAGUE_KEYS
from tmstats.snapshots import (FILE_TYPES, FORMAT_TYPES,
                               get_latest_snapshot_file)


logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
)

logger = logging.getLogger(__name__)
BACK_TO_LEAGUES_CALLBACK_DATA = 'back_to_leagues'


def build_league_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(LEAGUES[league_key].button_label,
                              callback_data=league_key)]
        for league_key in LEAGUE_KEYS
    ])


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
        [InlineKeyboardButton('Back',
                              callback_data=BACK_TO_LEAGUES_CALLBACK_DATA)],
    ])


def get_reply_target(update: Update):
    return update.effective_message or update.callback_query.message


def start(update: Update, _: CallbackContext):
    get_reply_target(update).reply_text(
        'Hi!\nI am GetFootballStats bot.\n'
        'I can send you the latest local league table '
        '(with recent form) or player stats snapshot '
        'in CSV or PDF format.\n'
        'Choose a league:',
        reply_markup=build_league_keyboard(),
    )


def button(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    callback_data = query.data

    if callback_data == BACK_TO_LEAGUES_CALLBACK_DATA:
        start(update, context)
        return

    if callback_data in LEAGUES:
        query.message.reply_text(
            'Choose which snapshot and format you want to download:',
            reply_markup=build_file_options_keyboard(callback_data),
        )
        return

    if not callback_data.startswith('file:'):
        return

    _, league, file_type, file_format = callback_data.split(':', 3)
    try:
        latest_snapshot = get_latest_snapshot_file(league, file_type, file_format)
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
    get_reply_target(update).reply_text(
        'Use /start to choose a league, then pick league table '
        'or player stats in CSV or PDF format.'
    )


def echo(update: Update, _: CallbackContext):
    update.message.reply_text(update.message.text)


def error(update: Update, context: CallbackContext):
    logger.warning('Update "%s" caused error "%s"', update, context.error)


def main():
    updater = Updater(get_bot_token(), use_context=True)
    dispatcher = updater.dispatcher

    print('Your bot is --->', updater.bot.username)

    dispatcher.add_handler(CommandHandler('start', start))
    dispatcher.add_handler(CommandHandler('help', help_command))
    dispatcher.add_handler(CallbackQueryHandler(button))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, echo))
    dispatcher.add_error_handler(error)

    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()
