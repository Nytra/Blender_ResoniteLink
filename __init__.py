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
import bmesh
from mathutils import Euler, Vector, Quaternion

# Resonitelink Imports
from resonitelink.models.datamodel import *
from resonitelink.proxies.datamodel.slot_proxy import SlotProxy
from resonitelink.proxies.datamodel.component_proxy import ComponentProxy
from resonitelink.models.assets.mesh.raw_data import TriangleSubmeshRawData
from resonitelink import ResoniteLinkClient, ResoniteLinkWebsocketClient

# Other imports
import logging
import asyncio
import threading
import traceback
from collections.abc import Callable

# Global setup
logger = logging.getLogger("TestLogger")
#logger.setLevel(logging.DEBUG)
#logging.disable(logging.DEBUG)
client : ResoniteLinkWebsocketClient
shutdown : bool = False
clientStarted : bool = False
clientError : bool = False
queuedActions : list[Callable[[bpy.types.Context], None]] = []
lock = threading.Lock()
lastError : str = ""

def b2u_coords(x, y, z):
    """
    Convert Blender coordinates to Unity coordinates.
    
    Parameters
    ----------
    x : float
        The Blender x coordinate
    y : float
        The Blender y coordinate
    z : float
        The Blender z coordinate
    
    Returns
    -------
    x : float
        The converted Unity x coordinate
    y : float
        The converted Unity y coordinate
    z : float
        The converted Unity z coordinate
    """
    
    #return -x, -z, y
    return -x, z, -y

def b2u_scale(x, y, z):
    """
    Convert Blender scales to Unity scales.
    
    Parameters
    ----------
    x : float
        The Blender x scale
    y : float
        The Blender y scale
    z : float
        The Blender z scale
    
    Returns
    -------
    x : float
        The converted Unity x scale
    y : float
        The converted Unity y scale
    z : float
        The converted Unity z scale
    """
    
    return x, z, y

def b2u_euler2quaternion(e):
    """
    Convert Blender Euler rotation to Unity quaternion.
    
    Parameters
    ----------
    e : mathutils.Euler
        The input Blender euler rotation
    
    Returns
    -------
    q : Quaternion
        The output Unity quaternion
    """
    
    return Euler((e.x, -e.z, -e.y), 'XYZ').to_quaternion()

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
    
    def GetData(self) -> bpy.types.ID:
        return self.id.data
    
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

    # def __init__(self, mesh : bpy.types.Mesh, slotProxy : SlotProxy):
    #     super().__init__(mesh.id_data, slotProxy)
    #     self._setup(mesh)

    def __init__(self, mesh : bpy.types.Mesh, slotProxy : SlotProxy):
        super().__init__(mesh.id_data, slotProxy)
        self._setup(mesh)
    
    def _setup(self, mesh : bpy.types.Mesh):
        self.meshComp : ComponentProxy = None
        self.matComps = [] # ComponentProxy = None
        self.meshRenderer : ComponentProxy = None
        self.UpdateMesh(mesh)

    def UpdateMesh(self, mesh : bpy.types.Mesh):
        self.mesh : bpy.types.Mesh = mesh

    # def GetObject(self) -> bpy.types.Object:
    #     for obj in bpy.data.objects:
    #          if obj == self.id:
    #              return obj
    #     return None
        

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

    # def invoke(self, context, event):
    #     wm = context.window_manager
    #     return wm.invoke_props_dialog(self)
    
    # def draw(self, context):
    #     global lastError

    #     layout = self.layout
    #     col = layout.column()
    #     col.label(text=lastError)

    #     # row = col.row()
    #     # row.prop(self, "my_float")
    #     # row.prop(self, "my_bool")

    #     # col.prop(self, "my_string")
    

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

        client = ResoniteLinkWebsocketClient(logger=logger)
        client.on_started(mainLoopAsync)
        client.on_stopped(onStoppedAsync)
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
        global clientStarted
        return context.scene is not None and clientStarted == True

    def execute(self, context):        # execute() is called when running the operator.
        global lock

        lock.acquire()

        queuedActions.append(lambda: self.sendSceneAsync(context))

        lock.release()

        return {'FINISHED'}            # Lets Blender know the operator finished successfully.
    
    async def updateSlotAsync(self, slotData : ObjectSlotData, context : bpy.types.Context):
        obj = slotData.GetObject()
        
        parentSlotData = objToSlotData[obj.parent] if obj.parent is not None else sceneToSlotData[context.scene]
        localPos = obj.matrix_local.translation
        localRotQ = b2u_euler2quaternion(obj.matrix_local.to_euler())
        localScale = obj.matrix_local.to_scale()
        await client.update_slot(
            slotData.slot,
            name=obj.name, 
            position=Float3(*b2u_coords(localPos.x, localPos.y, localPos.z)), 
            rotation=FloatQ(localRotQ.x, localRotQ.y, localRotQ.z, localRotQ.w),
            scale=Float3(*b2u_scale(localScale.x, localScale.y, localScale.z)),
            tag=obj.type,
            parent=parentSlotData.slot
        )
        
    async def addSlotAsync(self, obj : bpy.types.Object, context : bpy.types.Context) -> ObjectSlotData:
        parentSlotData = objToSlotData[obj.parent] if obj.parent is not None else sceneToSlotData[context.scene]
        localPos = obj.matrix_local.translation
        localRotQ = b2u_euler2quaternion(obj.matrix_local.to_euler())
        localScale = obj.matrix_local.to_scale()
        slot = await client.add_slot(
            name=obj.name,
            position=Float3(*b2u_coords(localPos.x, localPos.y, localPos.z)),
            rotation=FloatQ(localRotQ.x, localRotQ.y, localRotQ.z, localRotQ.w),
            scale=Float3(*b2u_scale(localScale.x, localScale.y, localScale.z)),
            tag=obj.type,
            parent=parentSlotData.slot
        )
        slotData = ObjectSlotData(obj, slot)
        objToSlotData[obj] = slotData
        return slotData
    
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

            slotData : ObjectSlotData
            slotData = await self.ensureSlotExistsForObjectAsync(obj, context)

            if obj.type == "MESH":
               # Evaluate mesh data with all current modifiers
                eval_obj = obj.evaluated_get(depsgraph)
                mesh = eval_obj.to_mesh()
                
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

                # Set up the mesh slot data for this object
                if not isinstance(slotData, MeshSlotData):
                    # New slot data
                    meshSlotData = MeshSlotData(obj.data, slotData.slot)
                    meshSlotData.id = obj
                    objToSlotData[obj] = meshSlotData
                else:
                    # Existing slot data
                    meshSlotData : MeshSlotData = slotData

                """
                bm : bmesh.types.BMesh = bmesh.new()
                bm.from_mesh(obj.data)
                if any(attr.name == "sharp_face" for attr in obj.data.attributes):
                    bmesh.ops.split_edges(bm, edges=bm.edges)
                bmesh.ops.reverse_faces(bm, faces=bm.faces)
                tris = bm.calc_loop_triangles()
                """

                # Get all UV Sets
                uv_layers = mesh.uv_layers
                
                # Get vertex color attributes (Limited to the first color group)
                vertex_colors = -1
                if (len(mesh.vertex_colors) > 0):
                    # Old way with vertex colors
                    vertex_colors = mesh.vertex_colors[0]
                else:
                    # New way with color attributes
                    if (len(mesh.color_attributes) > 0):
                        vertex_colors = mesh.color_attributes[0]

                # Save a dictionary of unique vertex hashes for fast indexing
                v_map = {}  # TODO: Make hashing faster probably
                idmax = 0   # Current maximum vertex ID
                
                # Create output lists
                verts = []  # Position data of each vertex (replicated)
                colors = []  # Currently limited to 1 color attribute per vertex
                normals = []  # Normals per vertex
                tangents = []  # TODO: Add tangents
                uvs = [[] for _ in uv_layers]  # List of uv lists per uv set
                submeshes = []  # List of triangle lists per material

                # Loop through all triangles and store their indices according
                # to their material ID
                tris = mesh.loop_triangles
                tri_map = {}  # A dictionary of material ID mapped to triangle indices
                for tri in tris:
                    # Get the material ID for this triangle
                    mat_id = mesh.polygons[tri.polygon_index].material_index
                    
                    # If the current material doesn't exist in the map add it
                    if (mat_id not in tri_map):
                        tri_map[mat_id] = []
                    
                    # Get loop indices
                    tri_loops = tri.loops
                    
                    # Append triangles to the submesh map (reverse winding order)
                    for loop_idx in reversed(tri_loops):
                        # Extract vertex information
                        vidx = mesh.loops[loop_idx].vertex_index
                        vpos = mesh.vertices[vidx].co
                        vnor = mesh.loops[loop_idx].normal
                        vuvs = [(layer.name, layer.data[loop_idx].uv) for layer in uv_layers]
                        vcol = vertex_colors.data[vidx].color if (vertex_colors != -1) else None
                        
                        # Construct a unique hash for the vertex
                        vhash = (
                            int(vidx),
                            (vnor.x, vnor.y, vnor.z),
                            tuple((name, uv.x, uv.y) for name, uv in vuvs),
                            (vcol[0], vcol[1], vcol[2], vcol[3]) if (vertex_colors != -1) else None
                        )
                        
                        # Check if the vertex exists uniquely and get its id
                        v_tid = -1
                        if (not vhash in v_map):
                            # Store the new index
                            v_map[vhash] = idmax
                            v_tid = idmax
                            idmax = idmax + 1
                            
                            # Store new data for this vertex
                            verts.append(Float3(
                                 *b2u_coords(vpos.x, vpos.y, vpos.z)
                            ))
                            if (vertex_colors != -1):
                                colors.append(Color(
                                    vcol[0], vcol[1], vcol[2], vcol[3]
                                ))
                            normals.append(Float3(
                                *b2u_coords(vnor[0], vnor[1], vnor[2])
                            ))
                            for uid, layer in enumerate(vuvs):
                                uvs[uid].append(layer[1][0])
                                uvs[uid].append(layer[1][1])
                        else:
                            # Retrieve the old index
                            v_tid = v_map[vhash]
                        
                        # Append the vertex index to the triangle map
                        tri_map[mat_id].append(v_tid)
                
                # Expand the triangle map into a list of lists (sorted by material id)
                for mid in sorted(tri_map):
                    submeshes.append(tri_map[mid])
                
                # TODO: Extract material information

                # Import the raw mesh data into Resonite
                asset_url = await client.import_mesh_raw_data(
                    positions=verts,
                    submeshes=[
                        TriangleSubmeshRawData(len(tri_indicies)//3, tri_indicies) for tri_indicies in submeshes
                    ],
                    colors=colors if (vertex_colors != -1) else None,
                    normals=normals,
                    uv_channel_dimensions=[2 for _ in uvs],  # Hard coded to U, V (2D)
                    uvs=uvs
                )  # TODO: Add tangents

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
                for mat in mesh.materials:
                    # TODO: Detect the material type
                    mat_type = "[FrooxEngine]FrooxEngine.PBS_VertexColorMetallic"
                    
                    # TODO: Detect whether the material exists already
                    matComp = await meshSlotData.slot.add_component(mat_type)
                    
                    # Add the material to the slot
                    meshSlotData.matComps.append(matComp)  # TODO: Put this material on the assets slot in the world
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
                elif newMesh or newMat:
                    await client.update_component(
                        meshSlotData.meshRenderer,
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
                #mesh.free_tangents()
                eval_obj.to_mesh_clear()
                
                #bm.free()
    

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
