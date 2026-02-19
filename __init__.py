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

import bpy
from resonitelink.models.datamodel import *
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
client : ResoniteLinkWebsocketClient
shutdown : bool = False
clientStarted : bool = False
clientError : bool = False
queuedActions : list[Callable[[bpy.types.Context], None]] = []
lock = threading.Lock()
lastError : str = ""

class ID_SlotData():

    def __init__(self, id : bpy.types.ID, slotProxy : SlotProxy):
        self.id : bpy.types.ID = id
        self.slot : SlotProxy = slotProxy


class ObjectSlotData(ID_SlotData):

    # def __init__(self, obj : bpy.types.Object, slotData : ID_Slot):
    #     super().__init__(obj, slotData.slot)

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


class MeshSlotData(ObjectSlotData):

    # def __init__(self, mesh : bpy.types.Mesh, slotData : ID_Slot):
    #     super().__init__(mesh.id_data, slotData.slot)
    #     self._setup(mesh)

    def __init__(self, mesh : bpy.types.Mesh, slotProxy : SlotProxy):
        super().__init__(mesh.id_data, slotProxy)
        self._setup(mesh)
    
    def _setup(self, mesh : bpy.types.Mesh):
        self.meshComp : ComponentProxy = None
        self.matComp : ComponentProxy = None
        self.meshRenderer : ComponentProxy = None
        self.UpdateMesh(mesh)

    def UpdateMesh(self, mesh : bpy.types.Mesh):
        self.mesh : bpy.types.Mesh = mesh
        

class SceneSlotData(ID_SlotData):

    pass
    
    # def __init__(self, scene : bpy.types.Scene, slotData : ID_Slot):
    #     super().__init__(scene, slotData.slot)


objToSlotData : dict[bpy.types.Object, ObjectSlotData] = {}
sceneToSlotData : dict[bpy.types.Scene, SceneSlotData] = {}

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
    bl_label = "ResoniteLink"
    bl_idname = "SCENE_PT_ResoniteLink"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"

    def draw(self, context):
        global clientStarted, clientError

        layout = self.layout

        if not bpy.app.online_access:
            row = layout.row()
            row.label(text="Please enable online-access.\nPreferences->System->Network")
            return

        #row = layout.row()
        #row.label(text="Hello world!", icon='WORLD_DATA')

        row = layout.row()
        row.label(text="Connection status: " + ("Connected" if clientStarted and not clientError else "Not connected" if not clientError else "ERROR"))

        row = layout.row()
        row.prop(context.scene, "ResoniteLink_port")

        row = layout.row()
        row.operator("scene.connect_resonitelink")

        row = layout.row()
        row.operator("scene.sendscene_resonitelink")

        row = layout.row()
        row.operator("scene.disconnect_resonitelink")

        row = layout.row()
        row.operator("scene.error_resonitelink")


class ErrorDialogOperator(bpy.types.Operator):
    bl_idname = "scene.error_resonitelink"
    bl_label = "View last error"

    @classmethod
    def poll(cls, context):
        global clientError
        return clientError

    def execute(self, context):
        global lastError
        self.report({'ERROR'}, lastError)
        return {'FINISHED'}

    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_props_dialog(self)
    

class DisconnectOperator(bpy.types.Operator):
    """Disconnect from the ResoniteLink websocket"""      # Use this as a tooltip for menu items and buttons.
    bl_idname = "scene.disconnect_resonitelink"        # Unique identifier for buttons and menu items to reference.
    bl_label = "Disconnect from ResoniteLink"         # Display name in the interface.
    bl_options = {'REGISTER'}
    
    @classmethod
    def poll(cls, context):
        global clientStarted, clientError
        return clientStarted and not clientError

    def execute(self, context):        # execute() is called when running the operator.
        global clientStarted, shutdown

        shutdown = True

        return {'FINISHED'}            # Lets Blender know the operator finished successfully.


class ConnectOperator(bpy.types.Operator):
    """Connect to the ResoniteLink websocket"""      # Use this as a tooltip for menu items and buttons.
    bl_idname = "scene.connect_resonitelink"        # Unique identifier for buttons and menu items to reference.
    bl_label = "Connect To ResoniteLink"         # Display name in the interface.
    bl_options = {'REGISTER'}
    
    @classmethod
    def poll(cls, context):
        global clientStarted
        return not clientStarted and bpy.app.online_access

    def execute(self, context):        # execute() is called when running the operator.
        global clientStarted

        threading.Thread(target=self.startResoLink, args=[context]).start()

        return {'FINISHED'}            # Lets Blender know the operator finished successfully.

    def startResoLink(self, context):
        global client, clientStarted, clientError, logger, queuedActions, shutdown, lastError

        client = ResoniteLinkWebsocketClient(log_level=logging.DEBUG, logger=logger)
        client.on_started(mainLoop)
        client.on_stopped(onStopped)
        port = context.scene.ResoniteLink_port
        clientError = False
        queuedActions = []
        shutdown = False
        clientStarted = False
        clientError = False

        try:
            asyncio.run(client.start(port))
        except Exception as e:
            lastError = "".join(line for line in traceback.format_exception(e))
            logger.log(logging.ERROR, "Error in websocket client thread:\n" + lastError)
            clientError = True

            # I don't know how to show the error dialog :(
            # None of these attempts below work

            #bpy.ops.scene.error_resonitelink('INVOKE_DEFAULT')

            #context.scene.operator_context = 'INVOKE_DEFAULT'
            #context.window_manager.operators.error_resonitelink()

            # with bpy.context.temp_override(window=context.window, area=context.area):
            #     bpy.ops.window_manager.error_resonitelink('INVOKE_DEFAULT')

        clientStarted = False
        

class SendSceneOperator(bpy.types.Operator):
    """Sends the current scene to ResoniteLink"""      # Use this as a tooltip for menu items and buttons.
    bl_idname = "scene.sendscene_resonitelink"        # Unique identifier for buttons and menu items to reference.
    bl_label = "Send Scene"         # Display name in the interface.
    bl_options = {'REGISTER'}  
    
    @classmethod
    def poll(cls, context):
        return context.scene is not None and clientStarted == True

    def execute(self, context):        # execute() is called when running the operator.
        global lock

        lock.acquire()

        queuedActions.append(lambda: self.doThing(context))

        lock.release()

        return {'FINISHED'}            # Lets Blender know the operator finished successfully.
    
    async def doThing(self, context):
        global client

        logger.log(logging.INFO, "context debug: " + context.scene.name)

        scene = context.scene

        sceneSlotData : SceneSlotData
        if not scene in sceneToSlotData.keys() or not await slotExists(sceneToSlotData[scene].slot):
            sceneSlot = await client.add_slot(name=scene.name, 
                                            position=Float3(0, 0, 0), 
                                            rotation=FloatQ(0, 0, 0, 1),
                                            scale=Float3(1, 1, 1),
                                            tag="SceneRoot")
            sceneSlotData = SceneSlotData(scene, sceneSlot)
            sceneToSlotData[scene] = sceneSlotData
        else:
            sceneSlotData = sceneToSlotData[scene]
            await client.update_slot(sceneSlotData.slot,
                                         name=scene.name)

        for obj in scene.objects:
            logger.log(logging.INFO, f"{obj.name}, {obj.type}")
            quat = obj.rotation_euler.to_quaternion()

            slotData : ObjectSlotData
            if not obj in objToSlotData.keys() or not await slotExists(objToSlotData[obj].slot):
                slot = await client.add_slot(name=obj.name, 
                                            position=Float3(obj.location.x, obj.location.y, obj.location.z), 
                                            rotation=FloatQ(quat.x, quat.y, quat.z, quat.w),
                                            scale=Float3(obj.scale.x, obj.scale.y, obj.scale.z),
                                            tag=obj.type,
                                            parent=sceneSlotData.slot)
                slotData = ObjectSlotData(obj, slot)
                objToSlotData[obj] = slotData
            else:
                slotData = objToSlotData[obj]
                await client.update_slot(slotData.slot,
                                         name=obj.name, 
                                         position=Float3(obj.location.x, obj.location.y, obj.location.z), 
                                         rotation=FloatQ(quat.x, quat.y, quat.z, quat.w),
                                         scale=Float3(obj.scale.x, obj.scale.y, obj.scale.z),
                                         tag=obj.type,
                                         parent=objToSlotData[obj.parent] if obj.parent is not None else sceneSlotData.slot)

            if obj.type == "MESH":

                mesh = obj.data

                if not isinstance(slotData, MeshSlotData):
                    meshSlotData = MeshSlotData(mesh, slotData.slot)
                    objToSlotData[obj] = meshSlotData
                else:
                    meshSlotData : MeshSlotData = slotData

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

#@client.on_started
async def mainLoop(client : ResoniteLinkClient):
    global shutdown, lock, clientStarted, clientError

    clientStarted = True

    #raise Exception("Test exception")

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

#@client.on_stopped
async def onStopped(client : ResoniteLinkClient):
    global clientStarted

    clientStarted = False

def register():
    bpy.utils.register_class(SendSceneOperator)
    bpy.utils.register_class(ResoniteLinkMainPanel)
    bpy.utils.register_class(ConnectOperator)
    bpy.utils.register_class(DisconnectOperator)
    bpy.utils.register_class(ErrorDialogOperator)
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
    bpy.utils.unregister_class(DisconnectOperator)
    bpy.utils.unregister_class(ErrorDialogOperator)
    #bpy.utils.unregister_class(BasicMenu)
    del bpy.types.Scene.ResoniteLink_port
    #bpy.types.VIEW3D_MT_object.remove(menu_func)

    shutdown = True


# This allows you to run the script directly from Blender's Text editor
# to test the add-on without having to install it.
# if __name__ == "__main__":
#     register()