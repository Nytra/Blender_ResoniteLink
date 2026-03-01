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
from resonitelink.exceptions import ResoniteLinkException

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

class ResoniteLinkController:
    
    logger : logging.Logger
    client : ResoniteLinkWebsocketClient
    shutdown : bool = False
    clientStarted : bool = False
    clientError : bool = False
    queuedActions : list[Callable[[bpy.types.Context], None]] = []
    lock = threading.Lock()
    lastError : str = ""

    sceneToResoniteLinkController : dict[bpy.types.Scene, 'ResoniteLinkController'] = {}

    @classmethod
    def Get(cls, scene : bpy.types.Scene):
        if scene in ResoniteLinkController.sceneToResoniteLinkController:
            return ResoniteLinkController.sceneToResoniteLinkController[scene]
        else:
            return ResoniteLinkController(scene=scene)
        
    @classmethod
    def ShutdownAll(cls):
        for controller in ResoniteLinkController.sceneToResoniteLinkController.values():
            controller.shutdown = True

    def __init__(self, scene : bpy.types.Scene):
        ResoniteLinkController.sceneToResoniteLinkController[scene] = self
    
    def startResoLink(self, context):

        self.logger = logging.getLogger("ResoniteLink")
        self.client = ResoniteLinkWebsocketClient(logger=self.logger)
        self.client.on_started(self.mainLoopAsync)
        self.client.on_stopped(self.onStoppedAsync)
        port = context.scene.ResoniteLink_port
        self.clientError = False
        self.queuedActions = []
        self.shutdown = False
        self.clientStarted = False
        self.clientError = False

        # if there was previously an exception in this controller's websocket thread, the lock might still be taken
        if self.lock.locked():
            self.lock.release()

        try:
            asyncio.run(self.client.start(port))
        except Exception as e:
            self.lastError = "".join(line for line in traceback.format_exception(e))
            self.logger.log(logging.ERROR, "Error in websocket client thread:\n" + self.lastError)
            self.clientError = True

        self.clientStarted = False

    async def mainLoopAsync(self, client : ResoniteLinkClient):

        self.clientStarted = True

        #raise Exception("Test exception")

        while (True):

            if len(self.queuedActions) > 0:
                self.lock.acquire()
                while len(self.queuedActions) > 0:
                    act = self.queuedActions[0]
                    await act()
                    self.queuedActions.remove(act)
                self.lock.release()

            if self.shutdown:
                await self.client.stop()
                break

            await asyncio.sleep(1)

    async def onStoppedAsync(self, client : ResoniteLinkClient):

        self.clientStarted = False
    
    async def sendSceneAsync(self, context : bpy.types.Context):

        self.logger.log(logging.INFO, "context debug: " + context.scene.name)

        # Get the main scene (TODO: Support multiple scenes)
        scene = context.scene

        # Create/Update the scene root slot
        sceneSlotData = SceneSlotData.Get(scene)
        if sceneSlotData is None:
            sceneSlotData = SceneSlotData(scene)
            await sceneSlotData.instantiateAsync(self.client, context)
        else:
            try:
                await sceneSlotData.updateAsync(self.client, context)
            except ResoniteLinkException:
                # slot was probably deleted
                await sceneSlotData.instantiateAsync(self.client, context)

        # Store the current evaluated dependency graph
        depsgraph = bpy.context.evaluated_depsgraph_get()

        for obj in scene.objects:
            self.logger.log(logging.INFO, f"{obj.name}, {obj.type}")
            self.logger.log(logging.INFO, f"- track axis: {obj.track_axis}")
            self.logger.log(logging.INFO, f"- up axis: {obj.up_axis}")
            self.logger.log(logging.INFO, f"- hide render: {obj.hide_render}")
            self.logger.log(logging.INFO, f"- hide viewport: {obj.hide_viewport}") # doesn't update?
            self.logger.log(logging.INFO, f"- visible: {obj.visible_get()}")

            objectSlotData = ObjectSlotData.Get(obj)
            if objectSlotData is None:
                objectSlotData = ObjectSlotData(obj)
                await objectSlotData.instantiateAsync(self.client, context)
            else:
                try:
                    await objectSlotData.updateAsync(self.client, context)
                except ResoniteLinkException:
                    # slot was probably deleted
                    await objectSlotData.instantiateAsync(self.client, context)

            self.logger.log(logging.INFO, f"{obj.name}, {obj.type} = {objectSlotData.slot.id}")

            # check if it's a type that stores mesh data 
            if obj.type in ["MESH", "CURVE", "SURFACE", "META", "FONT", "CURVES", "POINTCLOUD", "VOLUME", "GREASEPENCIL"]:

                # Grease pencil technically could work but needs extra code to handle it
                if obj.type == "GREASEPENCIL":
                    continue

                # Only show objects that are active in the render
                if obj.hide_render:
                    if isinstance(objectSlotData, MeshSlotData):
                        # mesh was sent previously
                        meshSlotData : MeshSlotData = objectSlotData
                        if not meshSlotData.hidden:
                            meshSlotData.hidden = True
                            try:
                                await self.client.update_component(
                                    meshSlotData.meshRenderer,
                                    Enabled=Field_Bool(value=False)
                                )
                            except ResoniteLinkException:
                                # renderer component probably got deleted
                                pass
                    continue

               # Evaluate mesh data with all current modifiers
                eval_obj : bpy.types.Object = obj.evaluated_get(depsgraph)

                # if obj.type == "GREASEPENCIL":
                #     gp : bpy.types.GreasePencil = eval_obj.data
                #     drawing : bpy.types.GreasePencilDrawing = gp.layers[0].frames[0].drawing
                #     logger.log(logging.INFO, f"grease pencil strokes: {drawing.strokes}") # strokes is documented on this page: https://developer.blender.org/docs/release_notes/4.3/grease_pencil_migration/

                mesh = eval_obj.to_mesh() # this can throw a RuntimeError in some cases, like for Grease pencil objects whose mesh data can't be accessed this way

                if len(mesh.vertices) == 0:
                    self.logger.log(logging.INFO, f"mesh has no vertices, skipping") # can happen in the case of metaballs- one of them will contain the whole mesh and the rest will be empty
                    eval_obj.to_mesh_clear()
                    continue

                # Set up the mesh slot data for this object
                if not isinstance(objectSlotData, MeshSlotData):
                    # New slot data
                    meshSlotData = MeshSlotData(obj)
                    meshSlotData.slot = objectSlotData.slot
                else:
                    # Existing slot data
                    meshSlotData : MeshSlotData = objectSlotData
                
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
                asset_url = await self.client.import_mesh_raw_data(**meshData)

                # Create/update the mesh component on the slot to point to the mesh data
                newMesh = False  # Mesh flag
                if meshSlotData.meshComp == None:
                    # TODO: Check for skinned/static
                    meshSlotData.meshComp = await meshSlotData.slot.add_component(
                        "[FrooxEngine]FrooxEngine.StaticMesh",
                        URL=Field_Uri(value=asset_url)
                    )
                    newMesh = True  # New mesh was created
                else:
                    # Update the existing mesh with the new uploaded data
                    try:
                        await self.client.update_component(
                            meshSlotData.meshComp,
                            URL=Field_Uri(value=asset_url)
                        )
                    except ResoniteLinkException:
                        # Previously existing component was probably deleted
                        meshSlotData.meshComp = await meshSlotData.slot.add_component(
                            "[FrooxEngine]FrooxEngine.StaticMesh",
                            URL=Field_Uri(value=asset_url)
                        )
                        newMesh = True  # New mesh was created

                # Add all materials to the asset slot if they don't exist already
                newMat = False  # Material flag
                matCount = len(mesh.materials)
                if matCount > 0 and len(meshSlotData.matComps) < matCount:
                    for mat in mesh.materials:
                        await meshSlotData.addMaterialAsync()
                    newMat = True
                elif matCount == 0 and len(meshSlotData.matComps) == 0:
                    # Add default material for debugging purposes
                    await meshSlotData.addMaterialAsync()
                    newMat = True

                # Create material component reference list
                mat_reflist = [
                    Reference(
                        target_type="[FrooxEngine]FrooxEngine.IAssetProvider<[FrooxEngine]FrooxEngine.Material>",
                        target_id=matComp.id
                    ) for matComp in meshSlotData.matComps
                ]

                # Create/update the material data
                if meshSlotData.meshRenderer == None:
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
                    try:
                        await self.client.update_component(
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
                    except ResoniteLinkException:
                        # comp was probably deleted
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

                # Clean up data
                if (hasattr(mesh, 'calc_normals_split')):
                    mesh.free_normals_split()
                else:
                    # mesh.customdata_custom_splitnormals_clear()
                    pass

                if meshData['tangents'] is not None:
                    mesh.free_tangents()
                
                eval_obj.to_mesh_clear()
        
        self.logger.log(logging.INFO, f"Done!")


class ResoniteLinkMainPanel(bpy.types.Panel):
    """Creates a ResoniteLink Panel in the Scene properties window"""
    bl_label = "ResoniteLink"
    bl_idname = "SCENE_PT_ResoniteLink"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"

    def draw(self, context):

        controller = ResoniteLinkController.Get(context.scene)

        layout = self.layout

        if not bpy.app.online_access:
            row = layout.row()
            row.label(text="Please enable online-access.\nPreferences->System->Network")
            return

        # row = layout.row()
        # row.label(text="Hello world!", icon='WORLD_DATA')

        row = layout.row()
        row.label(text="Connection status: " + ("Connected" if controller.clientStarted and not controller.clientError else "Not connected" if not controller.clientError else "ERROR"))

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
        controller = ResoniteLinkController.Get(context.scene)
        return controller.clientError

    def execute(self, context):
        controller = ResoniteLinkController.Get(context.scene)
        self.report({'ERROR'}, controller.lastError)
        return {'FINISHED'}
    

class DisconnectOperator(bpy.types.Operator):
    """Disconnect from the ResoniteLink websocket"""      # Use this as a tooltip for menu items and buttons.
    bl_idname = "scene.disconnect_resonitelink"        # Unique identifier for buttons and menu items to reference.
    bl_label = "Disconnect from ResoniteLink"         # Display name in the interface.
    bl_options = {'REGISTER'}
    
    @classmethod
    def poll(cls, context):
        controller = ResoniteLinkController.Get(context.scene)
        return controller.clientStarted and not controller.clientError

    def execute(self, context):        # execute() is called when running the operator.

        controller = ResoniteLinkController.Get(context.scene)
        controller.shutdown = True

        return {'FINISHED'}            # Lets Blender know the operator finished successfully.


class ConnectOperator(bpy.types.Operator):
    """Connect to the ResoniteLink websocket"""      # Use this as a tooltip for menu items and buttons.
    bl_idname = "scene.connect_resonitelink"        # Unique identifier for buttons and menu items to reference.
    bl_label = "Connect To ResoniteLink"         # Display name in the interface.
    bl_options = {'REGISTER'}
    
    @classmethod
    def poll(cls, context):
        controller = ResoniteLinkController.Get(context.scene)
        return not controller.clientStarted and bpy.app.online_access

    def execute(self, context):        # execute() is called when running the operator.

        controller = ResoniteLinkController.Get(context.scene)
        threading.Thread(target=controller.startResoLink, args=[context]).start()

        return {'FINISHED'}            # Lets Blender know the operator finished successfully.
        

class SendSceneOperator(bpy.types.Operator):
    """Sends the current scene to ResoniteLink"""      # Use this as a tooltip for menu items and buttons.
    bl_idname = "scene.sendscene_resonitelink"        # Unique identifier for buttons and menu items to reference.
    bl_label = "Send Scene"         # Display name in the interface.
    bl_options = {'REGISTER'}  
    
    @classmethod
    def poll(cls, context):
        controller = ResoniteLinkController.Get(context.scene)
        return context.scene is not None and controller.clientStarted == True and not (controller.lock.locked() or len(controller.queuedActions) > 0)

    def execute(self, context):        # execute() is called when running the operator.
        controller = ResoniteLinkController.Get(context.scene)

        controller.lock.acquire()

        controller.queuedActions.append(lambda: controller.sendSceneAsync(context))

        controller.lock.release()

        return {'FINISHED'}            # Lets Blender know the operator finished successfully.
    

def register():
    bpy.utils.register_class(SendSceneOperator)
    bpy.utils.register_class(ResoniteLinkMainPanel)
    bpy.utils.register_class(ConnectOperator)
    bpy.utils.register_class(DisconnectOperator)
    bpy.utils.register_class(ErrorDialogOperator)
    bpy.types.Scene.ResoniteLink_port = bpy.props.IntProperty(name="Websocket Port", default=2000, min=2000, max=65535)

def unregister():

    bpy.utils.unregister_class(SendSceneOperator)
    bpy.utils.unregister_class(ResoniteLinkMainPanel)
    bpy.utils.unregister_class(ConnectOperator)
    bpy.utils.unregister_class(DisconnectOperator)
    bpy.utils.unregister_class(ErrorDialogOperator)
    del bpy.types.Scene.ResoniteLink_port

    ResoniteLinkController.ShutdownAll()


# This allows you to run the script directly from Blender's Text editor
# to test the add-on without having to install it.
# if __name__ == "__main__":
#     register()
