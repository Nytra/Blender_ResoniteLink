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
    "blender": (4, 2, 0),
    "version": (0, 0, 1),
    "location": "",
    "warning": "",
    "category": "Generic",
}

import bpy
from resonitelink.models.datamodel import Float3, Field_String, FloatQ, Field_Uri, Reference, SyncList, Color, Component, Slot
from resonitelink.proxies.datamodel.slot_proxy import SlotProxy
from resonitelink.proxies.datamodel.component_proxy import ComponentProxy
from resonitelink.models.assets.mesh.raw_data import TriangleSubmeshRawData
from resonitelink.json import MISSING
from resonitelink import ResoniteLinkClient, ResoniteLinkWebsocketClient
import logging
import asyncio, threading, time
from collections.abc import Mapping

logger = logging.getLogger("TestLogger")
client = ResoniteLinkWebsocketClient(log_level=logging.DEBUG, logger=logger)
shutdown = False
clientStarted = False
currentContext : bpy.types.Context
queuedActions = []
lock = threading.Lock()
objToSlots = {}
sceneToSlots = {}

# class BasicMenu(bpy.types.Menu):
#     bl_idname = "SCENE_MT_ResoniteLink"
#     bl_label = "ResoniteLink"

#     def draw(self, context):
#         layout = self.layout

#         #layout.operator("object.select_all", text="Select/Deselect All").action = 'TOGGLE'
#         #layout.operator("object.select_all", text="Inverse").action = 'INVERT'
#         layout.operator("scene.test_resonitelink", text="Test ResoniteLink")

class ObjectSlotData:
    slotProxy : SlotProxy
    meshComp : ComponentProxy
    matComp : ComponentProxy
    meshRenderer : ComponentProxy

    def __init__(self, slotProxy):
        self.slotProxy = slotProxy
        self.meshComp = None
        self.matComp = None
        self.meshRenderer = None

class SceneSlotData:
    slotProxy : SlotProxy

    def __init__(self, slotProxy):
        self.slotProxy = slotProxy

async def slotExists(slotProxy : SlotProxy) -> bool:
    try:
        res = await slotProxy.fetch_data()
        logger.log(logging.INFO, res)
        return True
    except:
        return False

async def componentExists(compProxy : ComponentProxy) -> bool:
    try:
        res = await compProxy.fetch_data()
        logger.log(logging.INFO, res)
        return True
    except:
        return False

class HelloWorldPanel(bpy.types.Panel):
    """Creates a ResoniteLink Panel in the Scene properties window"""
    bl_label = "ResoniteLink Panel"
    bl_idname = "SCENE_PT_ResoniteLink"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"
    
    #port: 

    #bl_property = port

    def draw(self, context):
        layout = self.layout

        scene = context.scene

        row = layout.row()
        row.label(text="Hello world!", icon='WORLD_DATA')

        #row = layout.row()
        #row.label(text="Active object is: " + obj.name)

        #props = self.layout.operator('scene.test_resonitelink')
        #scene["ResoniteLink_port"] = 
        row = layout.row()
        row.prop(scene, "ResoniteLink_port")

        row = layout.row()
        row.operator("scene.connect_resonitelink")

        row = layout.row()
        row.operator("scene.test_resonitelink")


class ConnectResoniteLink(bpy.types.Operator):
    """Connect ResoniteLink"""      # Use this as a tooltip for menu items and buttons.
    bl_idname = "scene.connect_resonitelink"        # Unique identifier for buttons and menu items to reference.
    bl_label = "Connect ResoniteLink"         # Display name in the interface.
    bl_options = {'REGISTER'}
    
    @classmethod
    def poll(cls, context):
        global clientStarted
        return not clientStarted

    def execute(self, context):        # execute() is called when running the operator.
        global currentContext, clientStarted

        currentContext = context

        if not clientStarted:
            clientStarted = True
            threading.Thread(target=self.startResoLink).start()
            return {'FINISHED'}            # Lets Blender know the operator finished successfully.
        
        return {'CANCELLED'}

    def startResoLink(self):
        global client, currentContext

        port = currentContext.scene.ResoniteLink_port

        asyncio.run(client.start(port))
        

class TestResoniteLink(bpy.types.Operator):
    """Test ResoniteLink"""      # Use this as a tooltip for menu items and buttons.
    bl_idname = "scene.test_resonitelink"        # Unique identifier for buttons and menu items to reference.
    bl_label = "Test ResoniteLink"         # Display name in the interface.
    bl_options = {'REGISTER'}  # Enable undo for the operator.
    
    @classmethod
    def poll(cls, context):
        return context.scene is not None and clientStarted == True

    def execute(self, context):        # execute() is called when running the operator.
        global currentContext, lock

        currentContext = context

        lock.acquire()

        queuedActions.append(self.doThing)

        lock.release()

        return {'FINISHED'}            # Lets Blender know the operator finished successfully.
    
    async def doThing(self):
        global currentContext, client

        """ txt = "Hello from Blender!"

        # Adds a new slot. Since no parent was specified, it will be added to the world root by default.
        slot = await client.add_slot(name=txt, position=Float3(0, 1.5, 0))

        # Adds a TextRenderer component to the newly created slot.
        await slot.add_component("[FrooxEngine]FrooxEngine.TextRenderer",
            # Sets the initial value of the string field 'Text' on the component.
            Text=Field_String(value=txt)
        ) """

        scene = currentContext.scene

        sceneData : SceneSlotData
        if not scene in sceneToSlots.keys() or not await slotExists(sceneToSlots[scene].slotProxy):
            sceneSlotProxy = await client.add_slot(name=scene.name, 
                                            position=Float3(0, 0, 0), 
                                            rotation=FloatQ(0, 0, 0, 1),
                                            scale=Float3(1, 1, 1),
                                            tag="SceneRoot")
            sceneData = ObjectSlotData(sceneSlotProxy)
            sceneToSlots[scene] = sceneData
        else:
            sceneData = sceneToSlots[scene]
            await client.update_slot(sceneData.slotProxy,
                                         name=scene.name)

        for obj in scene.objects:
            logger.log(logging.INFO, f"{obj.name}, {obj.type}")
            quat = obj.rotation_euler.to_quaternion()

            slotData : ObjectSlotData
            if not obj in objToSlots.keys() or not await slotExists(objToSlots[obj].slotProxy):
                slotProxy = await client.add_slot(name=obj.data.name, 
                                            position=Float3(obj.location.x, obj.location.y, obj.location.z), 
                                            rotation=FloatQ(quat.x, quat.y, quat.z, quat.w),
                                            scale=Float3(obj.scale.x, obj.scale.y, obj.scale.z),
                                            tag=obj.data.id_type,
                                            parent=sceneData.slotProxy)
                slotData = ObjectSlotData(slotProxy)
                objToSlots[obj] = slotData
            else:
                slotData = objToSlots[obj]
                await client.update_slot(slotData.slotProxy,
                                         name=obj.data.name, 
                                         position=Float3(obj.location.x, obj.location.y, obj.location.z), 
                                         rotation=FloatQ(quat.x, quat.y, quat.z, quat.w),
                                         scale=Float3(obj.scale.x, obj.scale.y, obj.scale.z),
                                         tag=obj.data.id_type,
                                         parent=sceneData.slotProxy)

            if obj.data.id_type == "MESH":
                mesh = obj.to_mesh(preserve_all_data_layers=True)
                verts = []
                for vert in mesh.vertices:
                    verts.append(Float3(vert.co.x, vert.co.y, vert.co.z))
                tris = mesh.loop_triangles
                indices = []
                for tri in tris:
                    for idx in tri.vertices:
                        indices.append(idx)
                color_attrs = mesh.color_attributes
                colors = []
                for color_attr in color_attrs:
                    vals = color_attr.data
                    for dat in vals:
                        colors.append(Color(dat.color[0], dat.color[1], dat.color[2], dat.color[3]))
                normals = []
                for norm in mesh.vertex_normals:
                    normals.append(Float3(norm.vector.x, norm.vector.y, norm.vector.z))

                asset_url = await client.import_mesh_raw_data(positions=verts, submeshes=[ TriangleSubmeshRawData(len(tris), indices) ], colors=colors, normals=normals)

                newMesh = False
                if slotData.meshComp == None or not await componentExists(slotData.meshComp):
                    slotData.meshComp = await slotData.slotProxy.add_component("[FrooxEngine]FrooxEngine.StaticMesh",
                                    URL=Field_Uri(value=asset_url))
                    newMesh = True
                else:
                    await client.update_component(slotData.meshComp,
                                                  URL=Field_Uri(value=asset_url))

                newMat = False
                if slotData.matComp == None or not await componentExists(slotData.matComp):
                    slotData.matComp = await slotData.slotProxy.add_component("[FrooxEngine]FrooxEngine.PBS_VertexColorMetallic")
                    newMat = True

                if slotData.meshRenderer == None or not await componentExists(slotData.meshRenderer):
                    slotData.meshRenderer = await slotData.slotProxy.add_component("[FrooxEngine]FrooxEngine.MeshRenderer",
                                            Mesh=Reference(target_id=slotData.meshComp.id, target_type="[FrooxEngine]FrooxEngine.IAssetProvider<[FrooxEngine]FrooxEngine.Mesh>"),
                                            Materials=SyncList(Reference(target_type="[FrooxEngine]FrooxEngine.IAssetProvider<[FrooxEngine]FrooxEngine.Material>", target_id=slotData.matComp.id)))
                elif newMesh or newMat:
                    await client.update_component(slotData.meshRenderer, 
                                                  Mesh=Reference(target_id=slotData.meshComp.id, target_type="[FrooxEngine]FrooxEngine.IAssetProvider<[FrooxEngine]FrooxEngine.Mesh>"),
                                                  Materials=SyncList(Reference(target_type="[FrooxEngine]FrooxEngine.IAssetProvider<[FrooxEngine]FrooxEngine.Material>", target_id=slotData.matComp.id)))

                obj.to_mesh_clear()
    

# def menu_func(self, context):
#     self.layout.operator(TestResoniteLink.bl_idname)

@client.on_started
async def mainLoop(client : ResoniteLinkClient):
    global shutdown, currentContext, lock

    while (True):

        if len(queuedActions) > 0:
            lock.acquire()
            while len(queuedActions) > 0:
                act = queuedActions[0]
                await act()
                queuedActions.remove(act)
            lock.release()

        if shutdown:
            await client.stop()
            break

        await asyncio.sleep(1)

def register():
    #global clientStarted

    bpy.utils.register_class(TestResoniteLink)
    bpy.utils.register_class(HelloWorldPanel)
    bpy.utils.register_class(ConnectResoniteLink)
    #bpy.utils.register_class(BasicMenu)
    bpy.types.Scene.ResoniteLink_port = bpy.props.IntProperty(name="Websocket Port", default=2000, min=2000, max=65535)

    #bpy.types.TOPBAR_MT_file.append(BasicMenu.draw)
    #bpy.ops.wm.call_menu(name="SCENE_MT_ResoniteLink")
    #bpy.types.VIEW3D_MT_object.append(menu_func)  # Adds the new operator to an existing menu.

def unregister():
    global shutdown

    bpy.utils.unregister_class(TestResoniteLink)
    bpy.utils.unregister_class(HelloWorldPanel)
    bpy.utils.unregister_class(ConnectResoniteLink)
    #bpy.utils.unregister_class(BasicMenu)
    del bpy.types.Scene.ResoniteLink_port
    #bpy.types.VIEW3D_MT_object.remove(menu_func)

    shutdown = True


# This allows you to run the script directly from Blender's Text editor
# to test the add-on without having to install it.
# if __name__ == "__main__":
#     register()