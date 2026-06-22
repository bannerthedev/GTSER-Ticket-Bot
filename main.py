# requirements: pip install -U discord.py
import discord
from discord import app_commands
from discord.ext import commands
import os
import dotenv
from dotenv import load_dotenv

load_dotenv()


GUILD_ID = 1290693891862958112  # Guild ID where command registers
# Add as many staff role IDs as you want here:
STAFF_ROLE_IDS = [1518482686824681564, 1291073222099337335, 1290694789012127845, 1361629320518566050]  # example: [role_id1, role_id2, ...]

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree
ticket_counter = 1

# Build the embed and buttons for the menu
def menu_embed():
    e = discord.Embed(title="GTS Ticket Bot.", color=discord.Color.blurple())
    e.description = (
        "Open the ticket type that fits your issue best. Please read the Terms of Service before opening any ticket.\n"
        " before opening any ticket you need to know what you want. \n"
        "**Report A Player**\nReport a player for breaking the rules.\n"
        "**General Support**\nGet help with general questions or issues.\n"
    )
    return e

async def resolve_staff_entries(guild: discord.Guild, id_list):
    """Return two lists: (roles, members) resolved from id_list."""
    roles = []
    members = []
    for ident in id_list:
        # try role first
        role = guild.get_role(ident)
        if role:
            roles.append(role)
            continue
        # try member (cached or fetch)
        member = guild.get_member(ident)
        if member:
            members.append(member)
            continue
        try:
            member = await guild.fetch_member(ident)
            if member:
                members.append(member)
        except Exception:
            continue
    return roles, members

def is_staff_member(member: discord.Member):
    """Return True if member is admin, has a staff role, or their user id is in STAFF_ROLE_IDS."""
    if member.guild_permissions.administrator:
        return True
    if any(role.id in STAFF_ROLE_IDS for role in member.roles):
        return True
    if member.id in STAFF_ROLE_IDS:
        return True
    return False

class TicketMenuView(discord.ui.View):
    def __init__(self, category_id: int | None):
        super().__init__(timeout=None)
        self.category_id = category_id

    @discord.ui.button(label="Report A Player", style=discord.ButtonStyle.primary, custom_id="ticket_report_player")
    async def report_player_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await create_ticket_channel(interaction, "Report A Player", self.category_id, allow_attachments=False, allow_embeds=False)

    @discord.ui.button(label="General Support", style=discord.ButtonStyle.danger, custom_id="ticket_general_support")
    async def general_support_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await create_ticket_channel(interaction, "General Support", self.category_id, allow_attachments=False, allow_embeds=False)

    @discord.ui.button(label="Team's PFP's", style=discord.ButtonStyle.success, custom_id="ticket_teams_pfps")
    async def teams_pfps_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await create_ticket_channel(interaction, "Team's PFP's", self.category_id, allow_attachments=True, allow_embeds=True)

class AddMemberUserSelect(discord.ui.UserSelect):
    def __init__(self, invoker: discord.Member):
        super().__init__(placeholder="Select member(s) to add", min_values=1, max_values=5, custom_id="add_member_select")
        self.invoker = invoker

    async def callback(self, interaction: discord.Interaction):
        member = interaction.user
        is_staff = is_staff_member(member)

        topic = interaction.channel.topic or ""
        owner_id = None
        if topic.startswith("ticket_owner:"):
            try:
                owner_id = int(topic.split(":")[1].split("|")[0])
            except Exception:
                owner_id = None

        if not is_staff and owner_id != member.id:
            await interaction.response.send_message("Only staff or the ticket owner can add members to this ticket.", ephemeral=True)
            return

        added = []
        failed = []
        for user in self.values:
            try:
                await interaction.channel.set_permissions(user, overwrite=discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=True,
                    embed_links=True
                ))
                added.append(str(user))
            except Exception:
                failed.append(str(user))

        msg = ""
        if added:
            msg += f"Added: {', '.join(added)}.\n"
        if failed:
            msg += f"Failed: {', '.join(failed)}."
        await interaction.response.send_message(msg or "No changes made.", ephemeral=True)
        if self.view:
            self.view.stop()

class AddMemberSelect(discord.ui.View):
    def __init__(self, invoker: discord.Member):
        super().__init__(timeout=120)
        self.add_item(AddMemberUserSelect(invoker))

class CloseTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Add Member", style=discord.ButtonStyle.primary, custom_id="ticket_add_member")
    async def add_member_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        is_staff = is_staff_member(member)

        topic = interaction.channel.topic or ""
        owner_id = None
        if topic.startswith("ticket_owner:"):
            try:
                owner_id = int(topic.split(":")[1].split("|")[0])
            except Exception:
                owner_id = None

        if not is_staff and owner_id != member.id:
            await interaction.response.send_message("Only staff or the ticket owner can add members to this ticket.", ephemeral=True)
            return

        await interaction.response.send_message("Select member(s) to add (you have 2 minutes).", view=AddMemberSelect(member), ephemeral=True)

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, custom_id="ticket_close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        if is_staff_member(member):
            await interaction.response.send_message("Closing ticket...", ephemeral=True)
            await interaction.channel.delete(reason="Ticket closed")
            return

        topic = interaction.channel.topic or ""
        if topic.startswith("ticket_owner:"):
            owner_id = int(topic.split(":")[1].split("|")[0])
            if owner_id == interaction.user.id:
                await interaction.response.send_message("Closing ticket...", ephemeral=True)
                await interaction.channel.delete(reason="Ticket closed by owner")
                return

        await interaction.response.send_message("Only staff or the ticket owner can close this ticket.", ephemeral=True)

async def create_ticket_channel(interaction: discord.Interaction, type_label: str, category_id: int | None, allow_attachments: bool = False, allow_embeds: bool = False):
    global ticket_counter
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    safe_name = ''.join(ch for ch in interaction.user.name.lower() if ch.isalnum())[:8]
    channel_name = f"ticket-{ticket_counter}-{safe_name}"
    ticket_counter += 1

    # base overwrites: deny @everyone
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False)
    }

    # Member permissions: allow send/see, conditionally allow embed_links & attach_files
    overwrites[interaction.user] = discord.PermissionOverwrite(
        view_channel=True,
        send_messages=True,
        read_message_history=True,
        attach_files=allow_attachments,
        embed_links=allow_embeds
    )

    # Staff roles or user IDs: allow full access
    roles, members = await resolve_staff_entries(guild, STAFF_ROLE_IDS)
    for role in roles:
        overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True, embed_links=True, manage_channels=False)
    for member in members:
        overwrites[member] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True, embed_links=True)

    category = guild.get_channel(category_id) if category_id else None
    try:
        new_ch = await guild.create_text_channel(
            name=channel_name,
            topic=f"ticket_owner:{interaction.user.id} | type:{type_label}",
            overwrites=overwrites,
            category=category,
            reason=f"Ticket opened ({type_label}) by {interaction.user}"
        )

        embed = discord.Embed(
            title=f"{type_label} Ticket",
            description="Please describe the issue and provide any relevant evidence or details.",
            color=discord.Color.green()
        )
        await new_ch.send(content=interaction.user.mention, embed=embed, view=CloseTicketView())
        await interaction.followup.send(f"Ticket created: {new_ch.mention}", ephemeral=True)
    except Exception:
        await interaction.followup.send("Failed to create ticket channel. Check bot permissions.", ephemeral=True)

@tree.command(name="create_ticket", description="Post the ticket menu in a channel", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(channel="Channel to post the ticket menu in", category="Optional category to place ticket channels under")
@app_commands.checks.has_permissions(administrator=True)
async def create_ticket(interaction: discord.Interaction, channel: discord.TextChannel, category: discord.CategoryChannel | None = None):
    view = TicketMenuView(category.id if category else None)
    try:
        await channel.send(embed=menu_embed(), view=view)
        await interaction.response.send_message(f"Ticket menu posted in {channel.mention}.", ephemeral=True)
    except Exception:
        await interaction.response.send_message("Failed to post menu. Check bot permissions.", ephemeral=True)

@create_ticket.error
async def create_ticket_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.errors.MissingPermissions):
        await interaction.response.send_message("You need Administrator permission to use this command.", ephemeral=True)
    else:
        await interaction.response.send_message("An error occurred.", ephemeral=True)

@bot.event
async def on_ready():
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    print(f"Logged in as {bot.user}")

bot.run(os.getenv("TOKEN"))
