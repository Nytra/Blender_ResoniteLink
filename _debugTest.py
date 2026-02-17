""" from resonitelink.models.datamodel import Float3, Field_String
from resonitelink import ResoniteLinkClient, ResoniteLinkWebsocketClient
import logging
import asyncio

# Creates a new client that connects to ResoniteLink via websocket.
client = ResoniteLinkWebsocketClient(log_level=logging.DEBUG)

@client.on_started
async def on_client_started(client : ResoniteLinkClient):
        # Adds a new slot. Since no parent was specified, it will be added to the world root by default.
        slot = await client.add_slot(name="Hello World Slot", position=Float3(0, 1.5, 0))
    
        # Adds a TextRenderer component to the newly created slot.
        await slot.add_component("[FrooxEngine]FrooxEngine.TextRenderer",
            # Sets the initial value of the string field 'Text' on the component.
            Text=Field_String(value="Hello, world!")
        )

        await client.stop()

def register():
    # Asks for the current port ResoniteLink is running on.
    port = 41838

    # Start the client on the specified port.
    # asyncio.run(client.start(port))

    asyncio.run(client.start(port))


# # This allows you to run the script directly from Blender's Text editor
# # to test the add-on without having to install it.
if __name__ == "__main__":
    register() """