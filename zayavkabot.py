import os
import discord
from discord.ext import commands
import json
import re
from datetime import datetime
import traceback
import sys

# Получаем токен из переменных окружения Railway
TOKEN = os.environ.get('DISCORD_TOKEN')
if not TOKEN:
    print("❌ ОШИБКА: Переменная окружения DISCORD_TOKEN не установлена!")
    print("Установите DISCORD_TOKEN в настройках Railway")
    sys.exit(1)

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Файл для хранения заявок
APPLICATIONS_FILE = 'applications.json'
if 'RAILWAY_ENVIRONMENT' in os.environ:
    # На Railway сохраняем в /tmp
    APPLICATIONS_FILE = '/tmp/applications.json'

# ID каналов для основного сервера
LOGS_CHANNEL_ID = 1317565432210915379  # Канал для логов
APPLICATIONS_CATEGORY_ID = 1316900282340347934  # Категория для заявок

# ID ролей для тега и административных прав
TAG_ROLE_IDS = [
    1223589384452833290,
    1310673963000528949,
    1381682246678741022,
    1381685630555258931,
    1381683377090068550
]

# URL изображений для заявки
IMAGE_URL = "https://media.discordapp.net/attachments/1189879069991510066/1449528629775302698/zastavki-gas-kvas-com-n1e0-p-zastavki-na-telefon-am-nyam-2.png?ex=694285fc&is=6941347c&hm=560b40c38fbc83ae9821b60df73fadefb0d917eb0082f53635350b686b33b605&=&format=webp&quality=lossless"
SMALL_ICON_URL = "https://cdn.discordapp.com/attachments/1381981605848944720/1449946500057792543/4.png?ex=6940bf68&is=693f6de8&hm=df622f91cff0f82216929fb398fbc04aea2ab256c4323a18840538c0bbdabb08&"

class Application:
    def __init__(self, username_static, ooc_info, fam_history, reason, rollbacks, discord_user, discord_id, 
                 message_id=None, status="pending", channel_id=None, moderator=None, reason_reject=None):
        self.username_static = username_static
        self.ooc_info = ooc_info
        self.fam_history = fam_history
        self.reason = reason
        self.rollbacks = rollbacks
        self.discord_user = discord_user
        self.discord_id = discord_id
        self.message_id = message_id
        self.status = status
        self.channel_id = channel_id
        self.moderator = moderator
        self.reason_reject = reason_reject
        self.created_at = datetime.now()
        self.updated_at = datetime.now()

    def to_dict(self):
        return {
            "username_static": self.username_static,
            "ooc_info": self.ooc_info,
            "fam_history": self.fam_history,
            "reason": self.reason,
            "rollbacks": self.rollbacks,
            "discord_user": self.discord_user,
            "discord_id": self.discord_id,
            "message_id": self.message_id,
            "status": self.status,
            "channel_id": self.channel_id,
            "moderator": self.moderator,
            "reason_reject": self.reason_reject,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }

    @classmethod
    def from_dict(cls, data):
        app = cls(
            data["username_static"],
            data["ooc_info"],
            data["fam_history"],
            data["reason"],
            data["rollbacks"],
            data["discord_user"],
            data["discord_id"],
            data.get("message_id"),
            data.get("status", "pending"),
            data.get("channel_id"),
            data.get("moderator"),
            data.get("reason_reject")
        )
        app.created_at = datetime.fromisoformat(data.get("created_at", datetime.now().isoformat()))
        app.updated_at = datetime.fromisoformat(data.get("updated_at", datetime.now().isoformat()))
        return app

def save_applications(applications):
    try:
        with open(APPLICATIONS_FILE, 'w', encoding='utf-8') as f:
            data = [app.to_dict() for app in applications]
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Ошибка сохранения заявок: {e}")

def load_applications():
    try:
        with open(APPLICATIONS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            apps = []
            for item in data:
                try:
                    # Пытаемся загрузить с новым именем поля
                    app = Application.from_dict(item)
                    apps.append(app)
                except KeyError as e:
                    # Если не получилось, преобразуем старое имя в новое
                    if "username_static" not in item and "username static" in item:
                        # Конвертируем старый формат в новый
                        item["username_static"] = item.pop("username static")
                        item["ooc_info"] = item.get("ooc_info") or f"{item.get('ooc_name', '')} {item.get('age', '')}".strip()
                        
                        # Удаляем старые поля, если они есть
                        if "username" in item:
                            del item["username"]
                        if "static" in item:
                            del item["static"]
                        if "ooc_name" in item:
                            del item["ooc_name"]
                        if "age" in item:
                            del item["age"]
                        if "server_id" in item:
                            del item["server_id"]
                        
                        app = Application.from_dict(item)
                        apps.append(app)
                    else:
                        print(f"Ошибка загрузки записи: {e}, данные: {item}")
            return apps
    except FileNotFoundError:
        return []
    except json.JSONDecodeError:
        print("Ошибка чтения файла заявок. Создаю новый.")
        return []
    except Exception as e:
        print(f"Неизвестная ошибка при загрузке заявок: {e}")
        return []

applications = load_applications()

def has_admin_permission(user):
    """Проверяет, есть ли у пользователя одна из админских ролей"""
    try:
        for role_id in TAG_ROLE_IDS:
            role = discord.utils.get(user.roles, id=role_id)
            if role:
                return True
        return False
    except Exception as e:
        print(f"Ошибка проверки прав: {e}")
        return False

async def create_application_channel(guild, discord_user, discord_id, application):
    """Создает канал для заявки в указанной категории"""
    try:
        clean_name = re.sub(r'[^\w\s-]', '', discord_user)
        clean_name = re.sub(r'[-\s]+', '-', clean_name).strip().lower()
        
        channel_name = f"заявление-{clean_name}"
        
        # Используем фиксированный ID категории для заявок
        category = guild.get_channel(APPLICATIONS_CATEGORY_ID)
        if not category:
            category = await guild.create_category("Заявки")
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        }
        
        # Добавляем доступ для админских ролей
        for role_id in TAG_ROLE_IDS:
            role = guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    read_messages=True, 
                    send_messages=True, 
                    manage_messages=True, 
                    manage_channels=True
                )
        
        try:
            member = await guild.fetch_member(int(discord_id))
            overwrites[member] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        except:
            pass
        
        channel = await category.create_text_channel(
            name=channel_name,
            overwrites=overwrites,
            topic=f"Заявка от {application.username_static} | Discord: {discord_user} | ID: {discord_id}"
        )
        
        return channel
    except Exception as e:
        print(f"Ошибка создания канала: {e}")
        raise

async def delete_application_channel(channel, delay_seconds=5):
    """Удаляет канал заявки с задержкой (теперь 5 секунд вместо 300)"""
    import asyncio
    
    await asyncio.sleep(delay_seconds)
    try:
        await channel.delete(reason="Заявка обработана")
    except Exception as e:
        print(f"Ошибка при удалении канала: {e}")

async def send_application_embed(channel, application, interaction_user, guild):
    """Отправляет заявку в новом формате"""
    try:
        # Собираем теги для всех админских ролей
        role_mentions = []
        for role_id in TAG_ROLE_IDS:
            role = guild.get_role(role_id)
            if role:
                role_mentions.append(f"<@&{role.id}>")
        
        # Отправляем упоминания ролей
        if role_mentions:
            mentions_text = " ".join(role_mentions)
            await channel.send(f"{mentions_text} Новая заявка!")
        else:
            await channel.send("Новая заявка!")
        
        # Создаем Embed для заявки с временем
        embed = discord.Embed(
            title="Заявление",
            color=discord.Color.blue(),
            timestamp=application.created_at
        )
        
        # Добавляем поля
        embed.add_field(name="Никнейм Статик", value=f"```{application.username_static}```", inline=False)
        embed.add_field(name="OOC имя возраст", value=f"```{application.ooc_info}```", inline=False)
        embed.add_field(name="История семей", value=f"```{application.fam_history}```", inline=False)
        embed.add_field(name="Почему выбрали именно нас?", value=f"```{application.reason}```", inline=False)
        embed.add_field(name="Откаты с ГГ", value=f"```{application.rollbacks}```", inline=False)
        embed.add_field(name="Пользователь", value=f"<@{application.discord_id}>", inline=False)
        embed.add_field(name="Username", value=f"```{application.discord_user}```", inline=True)
        embed.add_field(name="ID", value=f"```{application.discord_id}```", inline=True)
        
        # Проверяем предыдущие заявки пользователя
        user_previous_apps = [app for app in applications 
                             if app.discord_id == application.discord_id 
                             and app.status != "pending"]
        
        if user_previous_apps:
            logs_channel = bot.get_channel(LOGS_CHANNEL_ID)
            log_links = []
            if logs_channel:
                async for message in logs_channel.history(limit=200):
                    if message.embeds:
                        for embed_msg in message.embeds:
                            # Ищем поле с ID пользователя в embed
                            user_found = False
                            user_id_in_embed = None
                            
                            # Проверяем все поля embed на наличие ID пользователя
                            for field in embed_msg.fields:
                                if field.value and application.discord_id in field.value:
                                    user_found = True
                                    user_id_in_embed = application.discord_id
                                    break
                            
                            # Также проверяем description и title
                            if not user_found and embed_msg.description and application.discord_id in embed_msg.description:
                                user_found = True
                                user_id_in_embed = application.discord_id
                            
                            if user_found and user_id_in_embed == application.discord_id:
                                # Определяем статус заявки
                                status_icon = "✅" if embed_msg.title and "✅" in embed_msg.title else "❌"
                                log_links.append(f"{status_icon} [Ссылка]({message.jump_url})")
                                break  # Нашли нужное сообщение, выходим из цикла по embed'ам
            
            if log_links:
                links_text = "\n".join(log_links[:5])  # Максимум 5 ссылок
                embed.add_field(
                    name="Предыдущие заявки",
                    value=links_text,
                    inline=False
                )
            else:
                embed.add_field(
                    name="Предыдущие заявки",
                    value="Заявок не найдено.",
                    inline=False
                )
        else:
            embed.add_field(
                name="Предыдущие заявки",
                value="Заявок не найдено.",
                inline=False
            )
        
        # Отправляем Embed
        message = await channel.send(embed=embed)
        
        # Создаем кнопки
        view = discord.ui.View(timeout=None)
        
        # Кнопка Принять
        async def approve_callback(interaction_btn: discord.Interaction):
            if not has_admin_permission(interaction_btn.user):
                await interaction_btn.response.send_message("❌ У вас нет прав для этого действия", ephemeral=True)
                return
            
            application.status = "approved"
            application.moderator = interaction_btn.user.name
            application.updated_at = datetime.now()
            save_applications(applications)
            
            try:
                user = await bot.fetch_user(int(application.discord_id))
                await user.send("🎉 **Вы приняты в семью!** 🎉\n\nДобро пожаловать! Ожидайте дальнейших инструкций от администрации.")
            except Exception as e:
                print(f"Не удалось отправить сообщение пользователю: {e}")
            
            await send_log_to_channel(application, interaction_btn.user, "approved", guild)
            
            try:
                await interaction_btn.message.edit(view=None)
            except:
                pass
            
            await channel.send(f"**Заявка принята рекрутом <@{interaction_btn.user.id}>**")
            bot.loop.create_task(delete_application_channel(channel))
            
            await interaction_btn.response.send_message("✅ Заявка принята! Канал будет удален через 5 секунд.", ephemeral=True)
        
        # Кнопка Отклонить
        async def reject_callback(interaction_btn: discord.Interaction):
            if not has_admin_permission(interaction_btn.user):
                await interaction_btn.response.send_message("❌ У вас нет прав для этого действия", ephemeral=True)
                return
            
            modal = discord.ui.Modal(title="Причина отказа")
            reason_input = discord.ui.TextInput(
                label="Укажите причину отказа",
                style=discord.TextStyle.paragraph,
                placeholder="Например: стрельба мушмент",
                required=True,
                max_length=500
            )
            modal.add_item(reason_input)
            
            async def modal_callback(modal_interaction: discord.Interaction):
                application.status = "rejected"
                application.moderator = interaction_btn.user.name
                application.reason_reject = reason_input.value
                application.updated_at = datetime.now()
                save_applications(applications)
                
                try:
                    user = await bot.fetch_user(int(application.discord_id))
                    await user.send(f"❌ **Ваша заявка отклонена.**\n\n**Причина:** {reason_input.value}\n\nВы можете подать заявку снова после устранения указанных замечаний.")
                except Exception as e:
                    print(f"Не удалось отправить сообщение пользователю: {e}")
                
                await send_log_to_channel(application, interaction_btn.user, "rejected", reason_input.value, guild)
                
                try:
                    await interaction_btn.message.edit(view=None)
                except:
                    pass
                
                await channel.send(f"**Заявка отклонена рекрутом <@{interaction_btn.user.id}>**\n**Причина:** {reason_input.value}")
                bot.loop.create_task(delete_application_channel(channel))
                
                await modal_interaction.response.send_message("✅ Заявка отклонена! Канал будет удален через 5 секунд.", ephemeral=True)
            
            modal.on_submit = modal_callback
            await interaction_btn.response.send_modal(modal)
        
        # Кнопка Взять на рассмотрение
        async def consider_callback(interaction_btn: discord.Interaction):
            if not has_admin_permission(interaction_btn.user):
                await interaction_btn.response.send_message("❌ У вас нет прав для этого действия", ephemeral=True)
                return
            
            # Сразу отвечаем
            await interaction_btn.response.defer()
            
            # Отправляем сообщение в канал
            await channel.send(f"**Заявка взята на рассмотрение рекрутом <@{interaction_btn.user.id}>**")
        
        # Создаем кнопки
        approve_button = discord.ui.Button(style=discord.ButtonStyle.green, label="Принять", row=0)
        approve_button.callback = approve_callback
        
        consider_button = discord.ui.Button(style=discord.ButtonStyle.blurple, label="Взять на рассмотрение", row=0)
        consider_button.callback = consider_callback
        
        reject_button = discord.ui.Button(style=discord.ButtonStyle.red, label="Отклонить", row=0)
        reject_button.callback = reject_callback
        
        view.add_item(approve_button)
        view.add_item(consider_button)
        view.add_item(reject_button)
        
        # Отправляем кнопки
        buttons_message = await channel.send(view=view)
        
        return message, buttons_message
    except Exception as e:
        print(f"Ошибка отправки embed: {e}")
        raise

async def send_log_to_channel(application, moderator, action, reason=None, guild=None):
    """Отправляет лог о заявке в канал логов"""
    try:
        logs_channel = bot.get_channel(LOGS_CHANNEL_ID)
        
        if not logs_channel:
            return
        
        embed = discord.Embed(
            title="✅ Заявка принята" if action == "approved" else "❌ Заявка отклонена",
            color=discord.Color.green() if action == "approved" else discord.Color.red(),
            timestamp=application.updated_at
        )
        
        embed.add_field(name="Никнейм Статик", value=application.username_static, inline=False)
        embed.add_field(name="OOC имя возраст", value=application.ooc_info, inline=False)
        
        if application.fam_history:
            embed.add_field(name="История семей", value=application.fam_history[:500] + "..." if len(application.fam_history) > 500 else application.fam_history, inline=False)
        
        if application.reason:
            embed.add_field(name="Причина выбора", value=application.reason[:500] + "..." if len(application.reason) > 500 else application.reason, inline=False)
        
        embed.add_field(name="Пользователь", value=f"<@{application.discord_id}>", inline=False)
        embed.add_field(name="Username", value=application.discord_user, inline=True)
        embed.add_field(name="ID", value=application.discord_id, inline=True)
        
        if action == "approved":
            embed.add_field(name="Принял", value=f"<@{moderator.id}>", inline=False)
        elif action == "rejected":
            embed.add_field(name="Отклонил", value=f"<@{moderator.id}>", inline=False)
            embed.add_field(name="Причина", value=reason[:500] + "..." if len(reason) > 500 else reason, inline=False)
        
        await logs_channel.send(embed=embed)
    except Exception as e:
        print(f"Ошибка отправки лога: {e}")

class ApplicationForm(discord.ui.Modal, title='Подача заявки в семью'):
    """Модальная форма для подачи заявки"""
    
    nickname_static = discord.ui.TextInput(
        label='Никнейм и Статик',
        placeholder='Например: Skeet Nyam 2253',
        max_length=100,
        required=True
    )
    
    ooc_info = discord.ui.TextInput(
        label='OOC имя и возраст',
        placeholder='Например: Серега 20',
        max_length=100,
        required=True
    )
    
    fam_history = discord.ui.TextInput(
        label='История семей',
        placeholder='Например: Gucci ушел в инактив',
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=True
    )
    
    reason = discord.ui.TextInput(
        label='Почему выбрали именно нас?',
        placeholder='Например: с маркета увидел, видел вас на контенте',
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=True
    )
    
    rollbacks = discord.ui.TextInput(
        label='Откаты с ГГ (ссылки)',
        placeholder='Например: https://youtu.be/ спешик',
        style=discord.TextStyle.paragraph,
        max_length=2000,
        required=False
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            # Проверяем, есть ли у пользователя активная заявка
            user_active_apps = [app for app in applications 
                               if app.discord_id == str(interaction.user.id) 
                               and app.status == "pending"]
            
            if user_active_apps:
                await interaction.response.send_message(
                    "❌ У вас уже есть активная заявка на рассмотрении!\n"
                    "Вы не можете подать новую заявку, пока предыдущая не будет обработана.",
                    ephemeral=True
                )
                return
            
            # Сразу отвечаем на взаимодействие
            await interaction.response.defer(ephemeral=True)
            
            application = Application(
                username_static=self.nickname_static.value.strip(),
                ooc_info=self.ooc_info.value.strip(),
                fam_history=self.fam_history.value,
                reason=self.reason.value,
                rollbacks=self.rollbacks.value if self.rollbacks.value else "Не указано",
                discord_user=interaction.user.name,
                discord_id=str(interaction.user.id)
            )
            
            applications.append(application)
            
            channel = await create_application_channel(interaction.guild, interaction.user.name, interaction.user.id, application)
            application.channel_id = channel.id
            
            message, buttons_message = await send_application_embed(channel, application, interaction.user, interaction.guild)
            application.message_id = message.id
            
            save_applications(applications)
            
            # Используем followup для отправки ответа
            await interaction.followup.send(
                f"✅ Ваша заявка успешно отправлена!\n\n"
                f"Заявка рассматривается в течение суток.\n"
                f"Ответ придёт в личные сообщения от бота.\n"
                f"Для обсуждения заявки создан канал: <#{application.channel_id}>",
                ephemeral=True
            )
            
        except Exception as e:
            print(f"Ошибка при создании заявки: {e}")
            traceback.print_exc()
            try:
                # Пытаемся отправить сообщение об ошибке через followup
                await interaction.followup.send(
                    "❌ Ошибка при создании заявки. Пожалуйста, попробуйте позже.", 
                    ephemeral=True
                )
            except:
                pass  # Если не получилось, просто игнорируем
    
    async def on_error(self, interaction: discord.Interaction, error: Exception):
        print(f"Ошибка в форме заявки: {error}")
        traceback.print_exc()
        try:
            # Используем followup для обработки ошибок
            await interaction.followup.send(
                '❌ Произошла ошибка при отправке заявки. Пожалуйста, попробуйте позже.', 
                ephemeral=True
            )
        except:
            pass  # Если не получилось, просто игнорируем

@bot.event
async def on_ready():
    print(f'✅ {bot.user} запущен!')
    print(f'ID бота: {bot.user.id}')
    
    # Выводим информацию о серверах
    for guild in bot.guilds:
        print(f'Сервер: {guild.name} (ID: {guild.id})')
        if guild.id == 1003525677640851496:
            print(f'  → Основной сервер: {guild.name}')
            print(f'  → Админские роли: {len(TAG_ROLE_IDS)}')
    
    print('Бот готов к работе!')

@bot.event
async def on_error(event, *args, **kwargs):
    print(f'Ошибка в событии {event}:')
    traceback.print_exc()

@bot.command(name="заявка")
async def create_application_panel(ctx):
    """Создает панель для подачи заявки"""
    try:
        # Проверяем права пользователя
        if not has_admin_permission(ctx.author) and not ctx.author.guild_permissions.administrator:
            await ctx.send("❌ У вас нет прав для выполнения этой команды.")
            return
        
        # Создаем Embed с обновленным дизайном
        embed = discord.Embed(
            title="**ЗАЯВКА В СЕМЬЮ**",
            color=discord.Color.from_rgb(0, 0, 0)  # Чёрный цвет
        )
        
        embed.add_field(
            name="**<a:wave:1449952532129517570> Путь в семью начинается здесь!**\n\u200b",
            value=(
                "**<:outputonlinepngtools:1449964820999700721> После заполнения анкеты Вам придет оповещение в ЛС от бота с результатом (ответ не придёт, если закрыт доступ к сообщениям в discord) **\n\n"
                "-# Заявка рассматривается в течении суток."
            ),
            inline=False
        )
        
        embed.set_image(url=IMAGE_URL)
        embed.set_footer(text="Amnyamov famq", icon_url=SMALL_ICON_URL)
        
        # Отправляем Embed с обновленной кнопкой
        class ApplicationButtonView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=None)
            
            @discord.ui.button(
                label="Подать заявку",
                emoji="<:icons848:1449967782308614244>",
                style=discord.ButtonStyle.gray,
                custom_id="apply_button_amnyamov",
                row=0
            )
            async def apply_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
                await interaction.response.send_modal(ApplicationForm())
        
        await ctx.send(embed=embed, view=ApplicationButtonView())
        bot.add_view(ApplicationButtonView())
        
    except Exception as e:
        print(f"Ошибка команды заявка: {e}")
        traceback.print_exc()
        await ctx.send("❌ Произошла ошибка при создании панели.")

@bot.command(name="заявки")
async def applications_list(ctx):
    """Показать все заявки"""
    try:
        if len(applications) == 0:
            await ctx.send("Заявок нет.")
            return
        
        embed = discord.Embed(
            title="📋 Активные заявки",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        
        pending_apps = [app for app in applications if app.status == "pending"]
        approved_apps = [app for app in applications if app.status == "approved"]
        rejected_apps = [app for app in applications if app.status == "rejected"]
        
        embed.add_field(name="⏳ На рассмотрении", value=str(len(pending_apps)), inline=True)
        embed.add_field(name="✅ Принято", value=str(len(approved_apps)), inline=True)
        embed.add_field(name="❌ Отклонено", value=str(len(rejected_apps)), inline=True)
        
        if pending_apps:
            apps_text = ""
            for app in pending_apps[-5:]:
                channel_info = f"<#{app.channel_id}>" if app.channel_id else "Канал не создан"
                apps_text += f"• **{app.username_static}** - {channel_info}\n"
            embed.add_field(name="Последние заявки:", value=apps_text, inline=False)
        
        await ctx.send(embed=embed)
    except Exception as e:
        print(f"Ошибка команды заявки: {e}")
        await ctx.send("❌ Произошла ошибка при получении списка заявок.")

@bot.command(name="очистка")
async def cleanup_channels(ctx):
    """Очистка старых каналов с заявками"""
    try:
        # Проверяем права пользователя
        if not has_admin_permission(ctx.author):
            await ctx.send("❌ У вас нет прав для выполнения этой команды.")
            return
        
        # Используем фиксированный ID категории
        category = ctx.guild.get_channel(APPLICATIONS_CATEGORY_ID)
        
        if not category:
            await ctx.send("Категория заявок не найдена.")
            return
        
        deleted = 0
        for channel in category.channels:
            if hasattr(channel, 'created_at'):
                age = datetime.now() - channel.created_at.replace(tzinfo=None)
                if age.days > 30:
                    try:
                        await channel.delete(reason="Очистка старых заявок")
                        deleted += 1
                    except:
                        pass
        
        await ctx.send(f"✅ Удалено {deleted} старых каналов с заявками.")
    except Exception as e:
        print(f"Ошибка команды очистка: {e}")
        await ctx.send("❌ Произошла ошибка при очистке каналов.")

@bot.command(name="статус")
async def application_status(ctx, discord_id: str = None):
    """Проверить статус заявки"""
    try:
        if discord_id is None:
            discord_id = str(ctx.author.id)
        
        user_apps = [app for app in applications if app.discord_id == discord_id]
        
        if not user_apps:
            await ctx.send("Заявок не найдено.")
            return
        
        embed = discord.Embed(
            title=f"Заявки пользователя <@{discord_id}>",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        
        for i, app in enumerate(user_apps[-3:], 1):
            status_emoji = "⏳" if app.status == "pending" else "✅" if app.status == "approved" else "❌"
            status_text = "На рассмотрении" if app.status == "pending" else "Принята" if app.status == "approved" else "Отклонена"
            
            app_info = f"**Статус:** {status_emoji} {status_text}\n"
            app_info += f"**Никнейм и статик:** {app.username_static}\n"
            
            if app.channel_id:
                app_info += f"**Канал:** <#{app.channel_id}>\n"
            
            if app.status == "rejected" and app.reason_reject:
                app_info += f"**Причина отказа:** {app.reason_reject[:100]}...\n"
            
            if app.status == "approved" and app.moderator:
                app_info += f"**Принял:** <@{next((m.id for m in ctx.guild.members if m.name == app.moderator), app.moderator)}>\n"
            
            app_info += f"**Дата:** {app.created_at.strftime('%d.%m.%Y %H:%M')}"
            
            embed.add_field(name=f"Заявка #{i}", value=app_info, inline=False)
        
        await ctx.send(embed=embed)
    except Exception as e:
        print(f"Ошибка команды статус: {e}")
        await ctx.send("❌ Произошла ошибка при проверке статуса.")

@bot.command(name="удалить_канал")
async def delete_channel_manual(ctx, channel_id: str = None):
    """Вручную удалить канал заявки"""
    try:
        # Проверяем права пользователя
        if not has_admin_permission(ctx.author):
            await ctx.send("❌ У вас нет прав для выполнения этой команды.")
            return
        
        if channel_id is None:
            # Проверяем, находится ли текущий канал в категории заявок
            category = ctx.guild.get_channel(APPLICATIONS_CATEGORY_ID)
            
            if category and ctx.channel.category_id == category.id:
                channel = ctx.channel
            else:
                await ctx.send("❌ Укажите ID канала или выполните команду в канале заявки.")
                return
        else:
            channel = ctx.guild.get_channel(int(channel_id))
        
        if not channel:
            await ctx.send("❌ Канал не найден.")
            return
        
        await channel.delete(reason="Ручное удаление администратором")
        await ctx.send(f"✅ Канал {channel.name} удален.")
    except Exception as e:
        print(f"Ошибка команды удалить_канал: {e}")
        await ctx.send(f"❌ Ошибка при удалении канала: {str(e)}")

@bot.command(name="тест")
async def test_command(ctx):
    """Тестовая команда для проверки работы бота"""
    await ctx.send(f"✅ Бот работает! Пинг: {round(bot.latency * 1000)}мс")

# Обработка ошибок команд
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ У вас недостаточно прав для выполнения этой команды.")
    else:
        print(f"Ошибка команды {ctx.command}: {error}")
        await ctx.send("❌ Произошла ошибка при выполнении команды.")

# Добавляем хендлер для перезапуска при ошибках
@bot.event
async def on_disconnect():
    print("Бот отключился. Пытаюсь переподключиться...")

# Запуск бота
if __name__ == "__main__":
    print("=" * 50)
    print("Запуск Discord бота для системы заявок")
    print(f"Токен получен: {'Да' if TOKEN else 'Нет'}")
    print("=" * 50)
    
    try:
        bot.run(TOKEN)
    except Exception as e:
        print(f"Критическая ошибка при запуске бота: {e}")
        traceback.print_exc()
        sys.exit(1)