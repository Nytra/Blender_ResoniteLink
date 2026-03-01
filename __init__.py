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

# Blender Imports
import bpy

# Resonitelink Imports
from resonitelink.models.datamodel import *
from resonitelink.proxies.datamodel.slot_proxy import SlotProxy
from resonitelink.proxies.datamodel.component_proxy import ComponentProxy
from resonitelink import ResoniteLinkClient, ResoniteLinkWebsocketClient

# Other imports
import logging
import asyncio
import threading
import traceback
from collections.abc import Callable
from typing import Any

# Add-on file imports
from .interop import *
from .asset_data import *

# Global setup
logger = logging.getLogger("ResoniteLink")
client : ResoniteLinkWebsocketClient
shutdown : bool = False
clientStarted : bool = False
clientError : bool = False
queuedActions : list[Callable[[bpy.types.Context], None]] = []
lock = threading.Lock()
lastError : str = ""
objToSlotData : dict[bpy.types.Object, ObjectSlotData] = {}
sceneToSlotData : dict[bpy.types.Scene, SceneSlotData] = {}

async def slotExistsAsync(slotProxy : SlotProxy) -> bool:
    exists : bool
    try:
        await slotProxy.fetch_data()
        exists = True
    except:
        exists = False
    
    logger.info(f"Slot {slotProxy.id}, exists: {exists}")
    return exists

async def componentExistsAsync(compProxy : ComponentProxy) -> bool:
    exists : bool
    try:
        await compProxy.fetch_data()
        exists = True
    except:
        exists = False

    logger.info(f"Slot {compProxy.id}, exists: {exists}")
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

        # row = layout.row()
        # row.label(text="Hello world!", icon='WORLD_DATA')

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
        global client, clientStarted, clientError, logger, queuedActions, shutdown, lastError, lock

        client = ResoniteLinkWebsocketClient(logger=logger)
        client.on_started(mainLoopAsync)
        client.on_stopped(onStoppedAsync)
        port = context.scene.ResoniteLink_port
        clientError = False
        queuedActions = []
        shutdown = False
        clientStarted = False
        clientError = False
        if lock.locked():
            lock.release()

        try:
            asyncio.run(client.start(port))
        except Exception as e:
            lastError = "".join(line for line in traceback.format_exception(e))
            logger.log(logging.ERROR, "Error in websocket client thread:\n" + lastError)
            clientError = True

        clientStarted = False
        

class SendSceneOperator(bpy.types.Operator):
    """Sends the current scene to ResoniteLink"""      # Use this as a tooltip for menu items and buttons.
    bl_idname = "scene.sendscene_resonitelink"        # Unique identifier for buttons and menu items to reference.
    bl_label = "Send Scene"         # Display name in the interface.
    bl_options = {'REGISTER'}  
    
    @classmethod
    def poll(cls, context):
        global clientStarted, lock, queuedActions
        return context.scene is not None and clientStarted == True and not (lock.locked() or len(queuedActions) > 0)

    def execute(self, context):        # execute() is called when running the operator.
        global lock

        lock.acquire()

        queuedActions.append(lambda: self.sendSceneAsync(context))

        lock.release()

        return {'FINISHED'}            # Lets Blender know the operator finished successfully.

    def getSlotKwargs(self, obj : bpy.types.Object, context : bpy.types.Context) -> dict[str, Any]:
        parentSlotData = objToSlotData[obj.parent] if obj.parent is not None else sceneToSlotData[context.scene]
        localPos = obj.matrix_local.translation.to_tuple()
        euler = obj.matrix_local.to_euler("XZY")
        localRotQ = b2u_euler2quaternion(euler)
        localScale = obj.matrix_local.to_scale().to_tuple() # could use obj.scale here which seems to preserve negative scale
        return {'name': obj.name,
                'position': Float3(*b2u_coords(*localPos)),
                'rotation': FloatQ(localRotQ.x, localRotQ.y, localRotQ.z, localRotQ.w),
                'scale': Float3(*b2u_scale(*localScale)),
                'tag': obj.type,
                'parent': parentSlotData.slot}
    
    async def updateSlotAsync(self, slotData : ObjectSlotData, context : bpy.types.Context):
        obj = slotData.GetObject()
        await client.update_slot(
            slot=slotData.slot,
            **self.getSlotKwargs(obj, context)
        )
        
    async def addSlotAsync(self, obj : bpy.types.Object, context : bpy.types.Context) -> ObjectSlotData:
        slot = await client.add_slot(
            **self.getSlotKwargs(obj, context)
        )
        slotData = ObjectSlotData(obj, slot)
        objToSlotData[obj] = slotData
        return slotData
    
    async def addMaterialAsync(self, meshSlotData : MeshSlotData):
        # TODO: Detect the material type
        mat_type = "[FrooxEngine]FrooxEngine.PBS_VertexColorMetallic"
        
        # TODO: Detect whether the material exists already
        matComp = await meshSlotData.slot.add_component(mat_type)
        
        # Add the material to the slot
        meshSlotData.matComps.append(matComp)  # TODO: Put this material on the assets slot in the world
    
    async def ensureSlotExistsForObjectAsync(self, obj : bpy.types.Object, context : bpy.types.Context) -> ObjectSlotData:
        slotData : ObjectSlotData

        if obj.parent is not None:# and not obj.parent in objToSlotData.keys():
            logger.log(logging.INFO, f"Making sure a slot exists for parent object: {obj.parent.name}, {obj.type}")
            await self.ensureSlotExistsForObjectAsync(obj.parent, context)

        if not obj in objToSlotData.keys() or not await slotExistsAsync(objToSlotData[obj].slot):
            slotData = await self.addSlotAsync(obj, context)
        else:
            slotData = objToSlotData[obj]
            await self.updateSlotAsync(slotData, context)
        
        logger.log(logging.INFO, f"{obj.name}, {obj.type} = {slotData.slot.id}")
        return slotData
    
    async def sendSceneAsync(self, context : bpy.types.Context):
        global client

        logger.log(logging.INFO, "context debug: " + context.scene.name)

        # Get the main scene (TODO: Support multiple scenes)
        scene = context.scene

        # Create/Update the scene root slot
        sceneSlotData : SceneSlotData
        if not scene in sceneToSlotData.keys() or not await slotExistsAsync(sceneToSlotData[scene].slot):
            sceneSlot = await client.add_slot(
                name=scene.name,
                position=Float3(0, 0, 0),
                rotation=FloatQ(0, 0, 0, 1),
                scale=Float3(1, 1, 1),
                tag="SceneRoot"
            )
            sceneSlotData = SceneSlotData(scene, sceneSlot)
            sceneToSlotData[scene] = sceneSlotData
        else:
            sceneSlotData = sceneToSlotData[scene]
            await client.update_slot(
                sceneSlotData.slot,
                name=scene.name
            )

        # Store the current evaluated dependency graph
        depsgraph = bpy.context.evaluated_depsgraph_get()

        for obj in scene.objects:
            logger.log(logging.INFO, f"{obj.name}, {obj.type}")
            logger.log(logging.INFO, f"- track axis: {obj.track_axis}")
            logger.log(logging.INFO, f"- up axis: {obj.up_axis}")
            logger.log(logging.INFO, f"- hide render: {obj.hide_render}")
            logger.log(logging.INFO, f"- hide viewport: {obj.hide_viewport}") # doesn't update?
            logger.log(logging.INFO, f"- visible: {obj.visible_get()}")

            slotData : ObjectSlotData
            slotData = await self.ensureSlotExistsForObjectAsync(obj, context)

            # check if it's a type that stores mesh data 
            if obj.type in ["MESH", "CURVE", "SURFACE", "META", "FONT", "CURVES", "POINTCLOUD", "VOLUME", "GREASEPENCIL"]:

                # Grease pencil technically could work but needs extra code to handle it
                if obj.type == "GREASEPENCIL":
                    continue

                # Only show objects that are active in the render
                if obj.hide_render:
                    if isinstance(slotData, MeshSlotData):
                        # mesh was sent previously
                        meshSlotData : MeshSlotData = slotData
                        if not meshSlotData.hidden:
                            meshSlotData.hidden = True
                            if await componentExistsAsync(meshSlotData.meshRenderer):
                                await client.update_component(
                                    meshSlotData.meshRenderer,
                                    Enabled=Field_Bool(value=False)
                                )
                    continue

               # Evaluate mesh data with all current modifiers
                eval_obj : bpy.types.Object = obj.evaluated_get(depsgraph)

                # if obj.type == "GREASEPENCIL":
                #     gp : bpy.types.GreasePencil = eval_obj.data
                #     drawing : bpy.types.GreasePencilDrawing = gp.layers[0].frames[0].drawing
                #     logger.log(logging.INFO, f"grease pencil strokes: {drawing.strokes}") # strokes is documented on this page: https://developer.blender.org/docs/release_notes/4.3/grease_pencil_migration/

                mesh = eval_obj.to_mesh() # this can throw a RuntimeError in some cases, like for Grease pencil objects whose mesh data can't be accessed this way

                if len(mesh.vertices) == 0:
                    logger.log(logging.INFO, f"mesh has no vertices, skipping") # can happen in the case of metaballs- one of them will contain the whole mesh and the rest will be empty
                    eval_obj.to_mesh_clear()
                    continue

                # Set up the mesh slot data for this object
                if not isinstance(slotData, MeshSlotData):
                    # New slot data
                    meshSlotData = MeshSlotData(obj, slotData.slot)
                    objToSlotData[obj] = meshSlotData
                else:
                    # Existing slot data
                    meshSlotData : MeshSlotData = slotData
                
                # Calculate custom normals
                if (hasattr(mesh, 'calc_normals_split')):
                    # Old method (4.0)
                    mesh.calc_normals_split()
                else:
                    # TODO: New method
                    #mesh.customdata_custom_splitnormals_add()
                    pass

                # Triangulate the evaluated mesh
                mesh.calc_loop_triangles()

                meshData = collectMeshData(mesh)

                # Import the raw mesh data into Resonite
                asset_url = await client.import_mesh_raw_data(**meshData)

                # Create/update the mesh component on the slot to point to the mesh data
                newMesh = False  # Mesh flag
                if meshSlotData.meshComp == None or not await componentExistsAsync(meshSlotData.meshComp):
                    # TODO: Check for skinned/static
                    meshSlotData.meshComp = await meshSlotData.slot.add_component(
                        "[FrooxEngine]FrooxEngine.StaticMesh",
                        URL=Field_Uri(value=asset_url)
                    )
                    newMesh = True  # New mesh was created
                else:
                    # Update the existing mesh with the new uploaded data
                    await client.update_component(
                        meshSlotData.meshComp,
                        URL=Field_Uri(value=asset_url)
                    )

                # Add all materials to the asset slot if they don't exist already
                newMat = False  # Material flag
                matCount = len(mesh.materials)
                if matCount > 0 and len(meshSlotData.matComps) < matCount:
                    for mat in mesh.materials:
                        await self.addMaterialAsync(meshSlotData)
                    newMat = True
                elif matCount == 0 and len(meshSlotData.matComps) == 0:
                    # Add default material for debugging purposes
                    await self.addMaterialAsync(meshSlotData)
                    newMat = True

                # Create material component reference list
                mat_reflist = [
                    Reference(
                        target_type="[FrooxEngine]FrooxEngine.IAssetProvider<[FrooxEngine]FrooxEngine.Material>",
                        target_id=matComp.id
                    ) for matComp in meshSlotData.matComps
                ]

                # Create/update the material data
                if meshSlotData.meshRenderer == None or not await componentExistsAsync(meshSlotData.meshRenderer):
                    # Add the mesh component to the slot
                    meshSlotData.meshRenderer = await meshSlotData.slot.add_component(
                        "[FrooxEngine]FrooxEngine.MeshRenderer",
                        Mesh=Reference(
                            target_id=meshSlotData.meshComp.id,
                            target_type="[FrooxEngine]FrooxEngine.IAssetProvider<[FrooxEngine]FrooxEngine.Mesh>"
                        ),
                        Materials=SyncList(
                            *mat_reflist
                        )
                    )
                elif newMesh or newMat or meshSlotData.hidden:
                    meshSlotData.hidden = False
                    await client.update_component(
                        meshSlotData.meshRenderer,
                        Mesh=Reference(
                            target_id=meshSlotData.meshComp.id,
                            target_type="[FrooxEngine]FrooxEngine.IAssetProvider<[FrooxEngine]FrooxEngine.Mesh>"
                        ),
                        Materials=SyncList(
                            *mat_reflist
                        ),
                        Enabled=Field_Bool(value=True)
                    )

                # Clean up data
                if (hasattr(mesh, 'calc_normals_split')):
                    mesh.free_normals_split()
                else:
                    # mesh.customdata_custom_splitnormals_clear()
                    pass

                if meshData['tangents'] is not None:
                    mesh.free_tangents()
                
                eval_obj.to_mesh_clear()
        
        logger.log(logging.INFO, f"Done!")
    

async def mainLoopAsync(client : ResoniteLinkClient):
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

async def onStoppedAsync(client : ResoniteLinkClient):
    global clientStarted

    clientStarted = False

def register():
    bpy.utils.register_class(SendSceneOperator)
    bpy.utils.register_class(ResoniteLinkMainPanel)
    bpy.utils.register_class(ConnectOperator)
    bpy.utils.register_class(DisconnectOperator)
    bpy.utils.register_class(ErrorDialogOperator)
    bpy.types.Scene.ResoniteLink_port = bpy.props.IntProperty(name="Websocket Port", default=2000, min=2000, max=65535)

def unregister():
    global shutdown

    bpy.utils.unregister_class(SendSceneOperator)
    bpy.utils.unregister_class(ResoniteLinkMainPanel)
    bpy.utils.unregister_class(ConnectOperator)
    bpy.utils.unregister_class(DisconnectOperator)
    bpy.utils.unregister_class(ErrorDialogOperator)
    del bpy.types.Scene.ResoniteLink_port

    shutdown = True


# This allows you to run the script directly from Blender's Text editor
# to test the add-on without having to install it.
# if __name__ == "__main__":
#     register()
