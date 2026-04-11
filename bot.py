import logging
from threading import Event
from urllib.parse import urlencode

import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (CallbackContext, CallbackQueryHandler,
                          CommandHandler, Filters, MessageHandler, Updater)

from config import get_app_base_url, get_bot_token
from tmstats.browse import (PLAYER_PAGE_SIZE, TEAM_PAGE_SIZE,
                            format_player_message, format_table_message,
                            format_team_summary, get_team_players,
                            get_team_row, load_league_snapshot)
from tmstats.catalog import LEAGUES, LEAGUE_KEYS


logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

BACK_TO_LEAGUES_CALLBACK_DATA = 'nav:leagues'
BROWSE_IN_CHAT_CALLBACK_DATA = 'nav:browse'
KEEPALIVE_EVENT = Event()


def mini_app_url(league: str = '') -> str:
    base_url = get_app_base_url()
    if not base_url:
        return ''

    query = urlencode({'league': league}) if league else ''
    suffix = f'?{query}' if query else ''
    return f'{base_url}/mini/{suffix}'


def telegram_api_request(method: str, payload: dict) -> dict:
    response = requests.post(
        f'https://api.telegram.org/bot{get_bot_token()}/{method}',
        json=payload,
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def render_raw_text(update: Update, text: str, reply_markup: dict):
    query = update.callback_query
    payload = {
        'text': text,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True,
        'reply_markup': reply_markup,
    }
    if query:
        payload.update({
            'chat_id': query.message.chat_id,
            'message_id': query.message.message_id,
        })
        telegram_api_request('editMessageText', payload)
        return

    payload['chat_id'] = update.effective_chat.id
    telegram_api_request('sendMessage', payload)


def render_text(update: Update, text: str, reply_markup: InlineKeyboardMarkup):
    query = update.callback_query
    if query:
        query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode='HTML',
            disable_web_page_preview=True,
        )
        return

    update.effective_message.reply_text(
        text=text,
        reply_markup=reply_markup,
        parse_mode='HTML',
        disable_web_page_preview=True,
    )


def build_league_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(LEAGUES[league_key].button_label,
                              callback_data=f'league:{league_key}')]
        for league_key in LEAGUE_KEYS
    ])


def build_start_webapp_keyboard() -> dict:
    return {
        'inline_keyboard': [
            [{'text': 'Open Mini App', 'web_app': {'url': mini_app_url()}}],
            [{'text': 'Browse in Chat', 'callback_data': BROWSE_IN_CHAT_CALLBACK_DATA}],
        ]
    }


def build_league_action_keyboard(league: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('View Table', callback_data=f'table:{league}')],
        [InlineKeyboardButton('Browse Teams', callback_data=f'teams:{league}:0')],
        [InlineKeyboardButton('Back', callback_data=BACK_TO_LEAGUES_CALLBACK_DATA)],
    ])


def build_table_keyboard(league: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('Browse Teams', callback_data=f'teams:{league}:0')],
        [InlineKeyboardButton('Back', callback_data=f'league:{league}')],
    ])


def build_team_list_keyboard(snapshot: dict, league: str,
                             page: int) -> InlineKeyboardMarkup:
    rows = snapshot['table_rows']
    page = max(0, min(page, max((len(rows) - 1) // TEAM_PAGE_SIZE, 0)))
    start = page * TEAM_PAGE_SIZE
    end = start + TEAM_PAGE_SIZE
    page_rows = rows[start:end]

    keyboard = [[
        InlineKeyboardButton(
            f'{row["rank"]}. {row["club"]} | {row["points"]} pts',
            callback_data=f'team:{league}:{row["rank"]}:0',
        )
    ] for row in page_rows]

    navigation = []
    if page > 0:
        navigation.append(
            InlineKeyboardButton('Prev', callback_data=f'teams:{league}:{page - 1}')
        )
    if end < len(rows):
        navigation.append(
            InlineKeyboardButton('Next', callback_data=f'teams:{league}:{page + 1}')
        )
    if navigation:
        keyboard.append(navigation)

    keyboard.append([InlineKeyboardButton('Back', callback_data=f'league:{league}')])
    return InlineKeyboardMarkup(keyboard)


def build_player_keyboard(league: str, rank: str, players: list,
                          page: int) -> InlineKeyboardMarkup:
    page = max(0, min(page, max((len(players) - 1) // PLAYER_PAGE_SIZE, 0)))
    start = page * PLAYER_PAGE_SIZE
    end = start + PLAYER_PAGE_SIZE
    page_players = players[start:end]
    keyboard = []

    for index in range(0, len(page_players), 2):
        button_row = []
        for player in page_players[index:index + 2]:
            shirt = f'#{player["shirtNumber"]} ' if player.get('shirtNumber') else ''
            button_row.append(
                InlineKeyboardButton(
                    f'{shirt}{player["name"]}',
                    callback_data=f'player:{league}:{player["id"]}:{rank}:{page}',
                )
            )
        keyboard.append(button_row)

    navigation = []
    if page > 0:
        navigation.append(
            InlineKeyboardButton('Prev', callback_data=f'team:{league}:{rank}:{page - 1}')
        )
    if end < len(players):
        navigation.append(
            InlineKeyboardButton('Next', callback_data=f'team:{league}:{rank}:{page + 1}')
        )
    if navigation:
        keyboard.append(navigation)

    keyboard.append([
        InlineKeyboardButton('Back to Teams', callback_data=f'teams:{league}:0'),
        InlineKeyboardButton('Back to League', callback_data=f'league:{league}'),
    ])
    return InlineKeyboardMarkup(keyboard)


def build_player_detail_keyboard(league: str, rank: str, page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('Back to Team', callback_data=f'team:{league}:{rank}:{page}')],
        [InlineKeyboardButton('Back to Teams', callback_data=f'teams:{league}:0')],
        [InlineKeyboardButton('Back to League', callback_data=f'league:{league}')],
    ])


def start(update: Update, _: CallbackContext):
    if mini_app_url():
        render_raw_text(
            update,
            (
                'Hi!\n'
                'I am <b>GetFootballStats bot</b>.\n'
                'Open the Mini App for the best browsing experience, '
                'or stay in chat if you prefer.'
            ),
            build_start_webapp_keyboard(),
        )
        return

    render_text(
        update,
        (
            'Hi!\n'
            'I am <b>GetFootballStats bot</b>.\n'
            'Choose a league to browse the latest local snapshot.'
        ),
        build_league_keyboard(),
    )


def show_league_actions(update: Update, league: str):
    render_text(
        update,
        (
            f'<b>{LEAGUES[league].label}</b>\n'
            'Choose what you want to see.'
        ),
        build_league_action_keyboard(league),
    )


def show_table(update: Update, league: str):
    snapshot = load_league_snapshot(league)
    render_text(update, format_table_message(snapshot), build_table_keyboard(league))


def show_team_list(update: Update, league: str, page: int):
    snapshot = load_league_snapshot(league)
    render_text(
        update,
        f'<b>{LEAGUES[league].label}</b>\nChoose a team.',
        build_team_list_keyboard(snapshot, league, page),
    )


def show_team(update: Update, league: str, rank: str, page: int):
    snapshot = load_league_snapshot(league)
    team_row = get_team_row(snapshot, rank)
    if not team_row:
        render_text(update, 'Team not found in the current snapshot.',
                    build_team_list_keyboard(snapshot, league, 0))
        return

    players = get_team_players(snapshot, team_row)
    render_text(
        update,
        format_team_summary(team_row, players),
        build_player_keyboard(league, rank, players, page),
    )


def show_player(update: Update, league: str, player_id: str, rank: str, page: int):
    snapshot = load_league_snapshot(league)
    team_row = get_team_row(snapshot, rank)
    player = snapshot['players_by_id'].get(player_id)

    if not team_row or not player:
        render_text(update, 'Player not found in the current snapshot.',
                    build_team_list_keyboard(snapshot, league, 0))
        return

    render_text(
        update,
        format_player_message(player, team_row),
        build_player_detail_keyboard(league, rank, page),
    )


def button(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    callback_data = query.data

    if callback_data == BACK_TO_LEAGUES_CALLBACK_DATA:
        start(update, context)
        return
    if callback_data == BROWSE_IN_CHAT_CALLBACK_DATA:
        render_text(
            update,
            (
                'Choose a league to browse the latest local snapshot.'
            ),
            build_league_keyboard(),
        )
        return

    parts = callback_data.split(':')
    action = parts[0]

    if action == 'league' and len(parts) == 2:
        show_league_actions(update, parts[1])
    elif action == 'table' and len(parts) == 2:
        show_table(update, parts[1])
    elif action == 'teams' and len(parts) == 3:
        show_team_list(update, parts[1], int(parts[2]))
    elif action == 'team' and len(parts) == 4:
        show_team(update, parts[1], parts[2], int(parts[3]))
    elif action == 'player' and len(parts) == 5:
        show_player(update, parts[1], parts[2], parts[3], int(parts[4]))


def help_command(update: Update, _: CallbackContext) -> None:
    app_url = mini_app_url()
    if app_url:
        update.effective_message.reply_text(
            'Use /start to open the Mini App, or choose Browse in Chat '
            'if you want the lightweight inline flow.'
        )
        return

    update.effective_message.reply_text(
        'Use /start to choose a league, view the current table, '
        'browse teams, and inspect player stats from the latest local snapshot.'
    )


def echo(update: Update, _: CallbackContext):
    update.message.reply_text('Use /start to browse league, team, and player data.')


def error(update: Update, context: CallbackContext):
    logger.warning('Update "%s" caused error "%s"', update, context.error)


def configure_menu_button():
    app_url = mini_app_url()
    if not app_url:
        return

    try:
        telegram_api_request('setChatMenuButton', {
            'menu_button': {
                'type': 'web_app',
                'text': 'Open Stats',
                'web_app': {
                    'url': app_url,
                },
            },
        })
    except requests.RequestException as exc:
        logger.warning('Could not set Mini App menu button: %s', exc)


def run_polling():
    updater = Updater(get_bot_token(), use_context=True)
    dispatcher = updater.dispatcher

    print('Your bot is --->', updater.bot.username)
    configure_menu_button()

    dispatcher.add_handler(CommandHandler('start', start))
    dispatcher.add_handler(CommandHandler('help', help_command))
    dispatcher.add_handler(CallbackQueryHandler(button))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, echo))
    dispatcher.add_error_handler(error)

    updater.start_polling()
    # The bot runs in a background thread when paired with the Mini App web
    # server, so it must not try to install process-wide signal handlers here.
    KEEPALIVE_EVENT.wait()


def main():
    run_polling()


if __name__ == '__main__':
    main()
