# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTIBILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

bl_info = {
    "name": "Blender_resonitelink",
    "author": "Nytra",
    "description": "",
    "blender": (2, 80, 0),
    "version": (0, 0, 1),
    "location": "",
    "warning": "",
    "category": "Generic",
}

import bpy
from resonitelink.models.datamodel import Float3, Field_String
from resonitelink import ResoniteLinkClient, ResoniteLinkWebsocketClient
import logging
import asyncio, threading

client = ResoniteLinkWebsocketClient(log_level=logging.DEBUG)
doThing = False
shutdown = False

class ObjectMoveX(bpy.types.Operator):
    """My Object Moving Script"""      # Use this as a tooltip for menu items and buttons.
    bl_idname = "object.move_x"        # Unique identifier for buttons and menu items to reference.
    bl_label = "Test ResoniteLink"         # Display name in the interface.
    bl_options = {'REGISTER', 'UNDO'}  # Enable undo for the operator.

    def execute(self, context):        # execute() is called when running the operator.
        global doThing

        doThing = True

        return {'FINISHED'}            # Lets Blender know the operator finished successfully.
    

def menu_func(self, context):
    self.layout.operator(ObjectMoveX.bl_idname)

@client.on_started
async def mainLoop(client : ResoniteLinkClient):
    global doThing

    while (True):
        if doThing:
            # Adds a new slot. Since no parent was specified, it will be added to the world root by default.
            slot = await client.add_slot(name="Hello World Slot", position=Float3(0, 1.5, 0))
    
            # Adds a TextRenderer component to the newly created slot.
            await slot.add_component("[FrooxEngine]FrooxEngine.TextRenderer",
                # Sets the initial value of the string field 'Text' on the component.
                Text=Field_String(value="Hello, world!")
            )

            doThing = False
        elif shutdown:
            await client.stop()
            break

        await asyncio.sleep(1)

def register():
    bpy.utils.register_class(ObjectMoveX)
    bpy.types.VIEW3D_MT_object.append(menu_func)  # Adds the new operator to an existing menu.

    threading.Thread(target=startResoLink).start()

def startResoLink():
    global client
    port = 41838
    asyncio.run(client.start(port))

def unregister():
    global shutdown

    bpy.utils.unregister_class(ObjectMoveX)
    bpy.types.VIEW3D_MT_object.remove(menu_func)

    shutdown = True
    

# This allows you to run the script directly from Blender's Text editor
# to test the add-on without having to install it.
# if __name__ == "__main__":
#     register()
#     doThing = True