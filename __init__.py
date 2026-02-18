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
from bpy import context
from resonitelink.models.datamodel import Float3, Field_String, FloatQ, Field_Uri, Reference, SyncList, Color
from resonitelink.models.assets.mesh.raw_data import TriangleSubmeshRawData
from resonitelink import ResoniteLinkClient, ResoniteLinkWebsocketClient
import logging
import asyncio, threading, time

logger = logging.getLogger("TestLogger")
client = ResoniteLinkWebsocketClient(log_level=logging.DEBUG, logger=logger)
shutdown = False
clientStarted = False
currentContext : bpy.types.Context
queuedActions = []
lock = threading.Lock()

class TestResoniteLink(bpy.types.Operator):
    """Test ResoniteLink"""      # Use this as a tooltip for menu items and buttons.
    bl_idname = "object.test_resonitelink"        # Unique identifier for buttons and menu items to reference.
    bl_label = "Test ResoniteLink"         # Display name in the interface.
    bl_options = {'REGISTER', 'UNDO'}  # Enable undo for the operator.

    portTest: bpy.props.IntProperty(name="Port", default=2, min=1, max=100)

    def execute(self, context):        # execute() is called when running the operator.
        global currentContext, lock

        currentContext = context

        lock.acquire()

        queuedActions.append(self.doThing)

        lock.release()

        return {'FINISHED'}            # Lets Blender know the operator finished successfully.
    
    async def doThing(self):
        global currentContext, client

        txt = "Hello from Blender!"

        # Adds a new slot. Since no parent was specified, it will be added to the world root by default.
        slot = await client.add_slot(name=txt, position=Float3(0, 1.5, 0))

        # Adds a TextRenderer component to the newly created slot.
        await slot.add_component("[FrooxEngine]FrooxEngine.TextRenderer",
            # Sets the initial value of the string field 'Text' on the component.
            Text=Field_String(value=txt)
        )

        scene = currentContext.scene
        for obj in scene.objects:
            slot = await client.add_slot(name=obj.data.name, 
                                         position=Float3(obj.location.x, obj.location.y, obj.location.z), 
                                         rotation=FloatQ(obj.rotation_euler.to_quaternion().x, obj.rotation_euler.to_quaternion().y, obj.rotation_euler.to_quaternion().z, obj.rotation_euler.to_quaternion().w),
                                         scale=Float3(obj.scale.x, obj.scale.y, obj.scale.z),
                                         tag=obj.data.id_type)
            logger.log(logging.INFO, obj.type)
            if obj.data.id_type == "MESH":
                mesh = obj.to_mesh()
                verts = []
                for vert in mesh.vertices.values():
                    verts.append(Float3(vert.co.x, vert.co.y, vert.co.z))
                tris = mesh.loop_triangles.values()
                indices = []
                for tri in tris:
                    for idx in tri.vertices:
                        indices.append(idx)
                color_attrs = mesh.color_attributes.values()
                colors = []
                for color_attr in color_attrs:
                    # color_attr is a bpy_prop_collection
                    vals = color_attr.data.values()
                    for dat in vals:
                        colors.append(Color(dat.color[0], dat.color[1], dat.color[2], dat.color[3]))
                        #logger.log(logging.INFO, dat.color)
                normals = []
                for norm in mesh.vertex_normals.values():
                    normals.append(Float3(norm.vector.x, norm.vector.y, norm.vector.z))
                asset_url = await client.import_mesh_raw_data(positions=verts, submeshes=[ TriangleSubmeshRawData(len(tris), indices) ], colors=colors, normals=normals)
                meshComp = await slot.add_component("[FrooxEngine]FrooxEngine.StaticMesh",
                                   URL=Field_Uri(value=asset_url))
                mat = await slot.add_component("[FrooxEngine]FrooxEngine.PBS_VertexColorMetallic")
                await slot.add_component("[FrooxEngine]FrooxEngine.MeshRenderer",
                                         Mesh=Reference(target_id=meshComp.id, target_type="[FrooxEngine]FrooxEngine.IAssetProvider<[FrooxEngine]FrooxEngine.Mesh>"),
                                         Materials=SyncList(Reference(target_type="[FrooxEngine]FrooxEngine.IAssetProvider<[FrooxEngine]FrooxEngine.Material>", target_id=mat.id)))
                
                obj.to_mesh_clear()
    

def menu_func(self, context):
    self.layout.operator(TestResoniteLink.bl_idname)

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
    global clientStarted

    bpy.utils.register_class(TestResoniteLink)
    bpy.types.VIEW3D_MT_object.append(menu_func)  # Adds the new operator to an existing menu.

    if not clientStarted:
        clientStarted = True
        threading.Thread(target=startResoLink).start()

def startResoLink():
    global client

    port = 38072

    asyncio.run(client.start(port))
        

def unregister():
    global shutdown

    bpy.utils.unregister_class(TestResoniteLink)
    bpy.types.VIEW3D_MT_object.remove(menu_func)

    shutdown = True


# This allows you to run the script directly from Blender's Text editor
# to test the add-on without having to install it.
# if __name__ == "__main__":
#     register()