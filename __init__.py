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
from resonitelink.models.datamodel import * #Float3, Field_String, FloatQ, Field_Uri, Reference, SyncList, Color, Component, Slot
from resonitelink.proxies.datamodel.slot_proxy import SlotProxy
from resonitelink.proxies.datamodel.component_proxy import ComponentProxy
from resonitelink.models.assets.mesh.raw_data import TriangleSubmeshRawData
from resonitelink import ResoniteLinkClient, ResoniteLinkWebsocketClient
import logging
import asyncio
import threading
import traceback
from collections.abc import Callable

logger = logging.getLogger("TestLogger")
client = ResoniteLinkWebsocketClient(log_level=logging.DEBUG, logger=logger)
shutdown = False
clientStarted = False
currentContext : bpy.types.Context
queuedActions : list[Callable[[bpy.types.Context], None]] = []
lock = threading.Lock()

class ID_Slot():

    def __init__(self, id : bpy.types.ID, slotProxy : SlotProxy):
        self.id : bpy.types.ID = id
        self.slot : SlotProxy = slotProxy


class ObjectSlot(ID_Slot):

    def __init__(self, obj : bpy.types.Object, slotProxy : SlotProxy):
        super().__init__(obj, slotProxy)

    def GetObject(self) -> bpy.types.Object:
        return self.id
    
    # Can multiple objects have the same data?
    # def GetObject(self) -> bpy.types.Object:
    #     for obj in bpy.data.objects:
    #         if obj.data == self.id:
    #             return obj
    #     return None


class MeshSlot(ObjectSlot):

    def __init__(self, mesh : bpy.types.Mesh, slotData : ID_Slot):
        super().__init__(mesh.id_data, slotData.slot)
        self._init(mesh)

    def __init__(self, mesh : bpy.types.Mesh, slotProxy : SlotProxy):
        super().__init__(mesh.id_data, slotProxy)
        self._init(mesh)
    
    def _init(self, mesh : bpy.types.Mesh):
        self.meshComp : ComponentProxy = None
        self.matComp : ComponentProxy = None
        self.meshRenderer : ComponentProxy = None
        self.UpdateMesh(mesh)

    def UpdateMesh(self, mesh : bpy.types.Mesh):
        self.mesh = mesh
        

class SceneSlot(ID_Slot):
    pass


objToSlotData : dict[bpy.types.Object, ObjectSlot] = {}
sceneToSlotData : dict[bpy.types.Scene, SceneSlot] = {}

# class BasicMenu(bpy.types.Menu):
#     bl_idname = "SCENE_MT_ResoniteLink"
#     bl_label = "ResoniteLink"

#     def draw(self, context):
#         layout = self.layout

#         #layout.operator("object.select_all", text="Select/Deselect All").action = 'TOGGLE'
#         #layout.operator("object.select_all", text="Inverse").action = 'INVERT'
#         layout.operator("scene.sendscene_resonitelink", text="Test ResoniteLink")


async def slotExists(slotProxy : SlotProxy) -> bool:
    exists : bool
    try:
        await slotProxy.fetch_data()
        exists = True
    except:
        exists = False
    
    logger.debug(f"Slot {slotProxy.id}, exists: {exists}")
    return exists

async def componentExists(compProxy : ComponentProxy) -> bool:
    exists : bool
    try:
        await compProxy.fetch_data()
        exists = True
    except:
        exists = False

    logger.debug(f"Slot {compProxy.id}, exists: {exists}")
    return exists

class ResoniteLinkMainPanel(bpy.types.Panel):
    """Creates a ResoniteLink Panel in the Scene properties window"""
    bl_label = "ResoniteLink Panel"
    bl_idname = "SCENE_PT_ResoniteLink"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"

    def draw(self, context):
        global clientStarted

        layout = self.layout

        scene = context.scene

        row = layout.row()
        row.label(text="Hello world!", icon='WORLD_DATA')

        row = layout.row()
        row.label(text="Connection status: " + "Connected" if clientStarted else "Not connected")

        row = layout.row()
        row.prop(scene, "ResoniteLink_port")

        row = layout.row()
        row.operator("scene.connect_resonitelink")

        row = layout.row()
        row.operator("scene.sendscene_resonitelink")


class ConnectOperator(bpy.types.Operator):
    """Connect to the ResoniteLink websocket"""      # Use this as a tooltip for menu items and buttons.
    bl_idname = "scene.connect_resonitelink"        # Unique identifier for buttons and menu items to reference.
    bl_label = "Connect To ResoniteLink"         # Display name in the interface.
    bl_options = {'REGISTER'}
    
    @classmethod
    def poll(cls, context):
        global clientStarted
        return not clientStarted

    def execute(self, context):        # execute() is called when running the operator.
        global currentContext, clientStarted

        currentContext = context

        threading.Thread(target=self.startResoLink).start()

        return {'FINISHED'}            # Lets Blender know the operator finished successfully.

    def startResoLink(self):
        global client, currentContext, clientStarted

        port = currentContext.scene.ResoniteLink_port

        try:
            asyncio.run(client.start(port))
        except Exception as e:
            logger.log(logging.ERROR, "Error in websocket client thread:\n" + "".join(line for line in traceback.format_exception(e)))

            # Create new client because the old one might be stuck in some bad state
            client = ResoniteLinkWebsocketClient(log_level=logging.DEBUG, logger=logger)
            clientStarted = False
        

class SendSceneOperator(bpy.types.Operator):
    """Sends the current scene to ResoniteLink"""      # Use this as a tooltip for menu items and buttons.
    bl_idname = "scene.sendscene_resonitelink"        # Unique identifier for buttons and menu items to reference.
    bl_label = "Send Scene"         # Display name in the interface.
    bl_options = {'REGISTER'}  # Enable undo for the operator.
    
    @classmethod
    def poll(cls, context):
        return context.scene is not None and clientStarted == True

    def execute(self, context):        # execute() is called when running the operator.
        global currentContext, lock

        currentContext = context

        lock.acquire()

        queuedActions.append(lambda: self.doThing(context))

        lock.release()

        return {'FINISHED'}            # Lets Blender know the operator finished successfully.
    
    async def doThing(self, context):
        global currentContext, client

        logger.log(logging.INFO, "context debug: " + context.scene.name)

        scene = currentContext.scene

        sceneRootSlotData : SceneSlot
        if not scene in sceneToSlotData.keys() or not await slotExists(sceneToSlotData[scene].slot):
            sceneSlot = await client.add_slot(name=scene.name, 
                                            position=Float3(0, 0, 0), 
                                            rotation=FloatQ(0, 0, 0, 1),
                                            scale=Float3(1, 1, 1),
                                            tag="SceneRoot")
            sceneRootSlotData = SceneSlot(scene, sceneSlot)
            sceneToSlotData[scene] = sceneRootSlotData
        else:
            sceneRootSlotData = sceneToSlotData[scene]
            await client.update_slot(sceneRootSlotData.slot,
                                         name=scene.name)

        for obj in scene.objects:
            logger.log(logging.INFO, f"{obj.name}, {obj.type}")
            quat = obj.rotation_euler.to_quaternion()

            slotData : ObjectSlot
            if not obj in objToSlotData.keys() or not await slotExists(objToSlotData[obj].slot):
                slot = await client.add_slot(name=obj.data.name, 
                                            position=Float3(obj.location.x, obj.location.y, obj.location.z), 
                                            rotation=FloatQ(quat.x, quat.y, quat.z, quat.w),
                                            scale=Float3(obj.scale.x, obj.scale.y, obj.scale.z),
                                            tag=obj.data.id_type,
                                            parent=sceneRootSlotData.slot)
                slotData = ObjectSlot(obj, slot)
                objToSlotData[obj] = slotData
            else:
                slotData = objToSlotData[obj]
                await client.update_slot(slotData.slot,
                                         name=obj.data.name, 
                                         position=Float3(obj.location.x, obj.location.y, obj.location.z), 
                                         rotation=FloatQ(quat.x, quat.y, quat.z, quat.w),
                                         scale=Float3(obj.scale.x, obj.scale.y, obj.scale.z),
                                         tag=obj.data.id_type,
                                         parent=objToSlotData[obj.parent] if obj.parent is not None else sceneRootSlotData.slot)

            if obj.data.id_type == "MESH":

                mesh = obj.data

                if not isinstance(slotData, MeshSlot):
                    meshSlotData = MeshSlot(mesh, slotData.slot)
                    objToSlotData[obj] = meshSlotData
                else:
                    meshSlotData : MeshSlot = slotData

                #mesh = obj.to_mesh(preserve_all_data_layers=True)

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
                if meshSlotData.meshComp == None or not await componentExists(meshSlotData.meshComp):
                    meshSlotData.meshComp = await meshSlotData.slot.add_component("[FrooxEngine]FrooxEngine.StaticMesh",
                                    URL=Field_Uri(value=asset_url))
                    newMesh = True
                else:
                    await client.update_component(meshSlotData.meshComp,
                                                  URL=Field_Uri(value=asset_url))

                newMat = False
                if meshSlotData.matComp == None or not await componentExists(meshSlotData.matComp):
                    meshSlotData.matComp = await meshSlotData.slot.add_component("[FrooxEngine]FrooxEngine.PBS_VertexColorMetallic")
                    newMat = True

                if meshSlotData.meshRenderer == None or not await componentExists(meshSlotData.meshRenderer):
                    meshSlotData.meshRenderer = await meshSlotData.slot.add_component("[FrooxEngine]FrooxEngine.MeshRenderer",
                                            Mesh=Reference(target_id=meshSlotData.meshComp.id, target_type="[FrooxEngine]FrooxEngine.IAssetProvider<[FrooxEngine]FrooxEngine.Mesh>"),
                                            Materials=SyncList(Reference(target_type="[FrooxEngine]FrooxEngine.IAssetProvider<[FrooxEngine]FrooxEngine.Material>", target_id=meshSlotData.matComp.id)))
                elif newMesh or newMat:
                    await client.update_component(meshSlotData.meshRenderer, 
                                                  Mesh=Reference(target_id=meshSlotData.meshComp.id, target_type="[FrooxEngine]FrooxEngine.IAssetProvider<[FrooxEngine]FrooxEngine.Mesh>"),
                                                  Materials=SyncList(Reference(target_type="[FrooxEngine]FrooxEngine.IAssetProvider<[FrooxEngine]FrooxEngine.Material>", target_id=meshSlotData.matComp.id)))

                #obj.to_mesh_clear()
    

# def menu_func(self, context):
#     self.layout.operator(TestResoniteLink.bl_idname)

@client.on_started
async def mainLoop(client : ResoniteLinkClient):
    global shutdown, currentContext, lock, clientStarted

    clientStarted = True

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

@client.on_stopped
async def onStopped(client : ResoniteLinkClient):
    global clientStarted

    clientStarted = False

def register():
    bpy.utils.register_class(SendSceneOperator)
    bpy.utils.register_class(ResoniteLinkMainPanel)
    bpy.utils.register_class(ConnectOperator)
    #bpy.utils.register_class(BasicMenu)
    bpy.types.Scene.ResoniteLink_port = bpy.props.IntProperty(name="Websocket Port", default=2000, min=2000, max=65535)

    #bpy.types.TOPBAR_MT_file.append(BasicMenu.draw)
    #bpy.ops.wm.call_menu(name="SCENE_MT_ResoniteLink")
    #bpy.types.VIEW3D_MT_object.append(menu_func)  # Adds the new operator to an existing menu.

def unregister():
    global shutdown

    bpy.utils.unregister_class(SendSceneOperator)
    bpy.utils.unregister_class(ResoniteLinkMainPanel)
    bpy.utils.unregister_class(ConnectOperator)
    #bpy.utils.unregister_class(BasicMenu)
    del bpy.types.Scene.ResoniteLink_port
    #bpy.types.VIEW3D_MT_object.remove(menu_func)

    shutdown = True


# This allows you to run the script directly from Blender's Text editor
# to test the add-on without having to install it.
# if __name__ == "__main__":
#     register()