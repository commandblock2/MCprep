# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####


import os

import bpy
from bpy_extras.io_utils import ImportHelper

from .. import conf
from . import generate
from . import sequences
from .. import tracking
from .. import util
from . import uv_tools


# -----------------------------------------------------------------------------
# Material class functions
# -----------------------------------------------------------------------------
class McprepMaterialProps():
	"""Class to inheret reused MCprep settings.

	Benefit is to also enforce the same options, required where exec funcitons
	pass through from one operator to the other (e.g. prep mats on swap packs)
	"""
	animateTextures = bpy.props.BoolProperty(
		name="Animate textures (may be slow first time)",
		description=(
			"Swap still images for the animated sequenced found in "
			"the active or default texture pack."),
		default=False)
	autoFindMissingTextures = bpy.props.BoolProperty(
		name="Find missing images",
		description=(
			"If the texture for an existing material is missing, try "
			"to load from the default texture pack instead"),
		default=True)
	combineMaterials = bpy.props.BoolProperty(
		name="Combine materials",
		description="Consolidate duplciate materials & textures",
		default=False)
	improveUiSettings = bpy.props.BoolProperty(
		name="Improve UI",
		description="Automatically improve relevant UI settings",
		default=True)
	usePrincipledShader = bpy.props.BoolProperty(
		name="Use Principled Shader (if available)",
		description=(
			"If available and using cycles, build materials using the "
			"principled shader"),
		default=True)
	useReflections = bpy.props.BoolProperty(
		name="Use reflections",
		description="Allow appropriate materials to be rendered reflective",
		default=True)
	useExtraMaps = bpy.props.BoolProperty(
		name="Use extra maps",
		description=(
			"load other image passes like normal and "
			"spec maps if available"),
		default=True)
	normalIntensity = bpy.props.FloatProperty(
		name="Normal map intensity",
		description=(
			"Set normal map intensity, if normal maps are found in "
			"the active texture pack and using normal/spec passes"),
		default=1.0,
		max=1,
		min=0)
	makeSolid = bpy.props.BoolProperty(
		name="Make all materials solid",
		description="Make all materials solid only, for shadows and rendering",
		default=False)
	syncMaterials = bpy.props.BoolProperty(
		name="Sync materials",
		description=(
			"Synchronize materials with those in the active "
			"pack's materials.blend file"),
		default=True)
	packFormat = bpy.props.EnumProperty(
		name="Pack Format",
		description="Change the pack format when using a PBR resource pack.",
		items=[
			("simple", "Simple (no PBR)",
				"Use a simple shader setup with no PBR or emission falloff."),
			("specular", "Specular", "Sets the pack format to Specular."),
			("seus", "SEUS", "Sets the pack format to SEUS.")]
	)


def draw_mats_common(self, context):
	row = self.layout.row()
	col = row.column()
	engine = context.scene.render.engine
	if engine == 'CYCLES' or engine == 'BLENDER_EEVEE':
		col.prop(self, "packFormat")
		col.prop(self, "usePrincipledShader")
	col.prop(self, "useReflections")
	col.prop(self, "makeSolid")
	col.prop(self, "animateTextures")
	col.prop(self, "autoFindMissingTextures")

	row = self.layout.row()
	row.prop(self, "useExtraMaps")
	row.prop(self, "syncMaterials")

	# col = row.column()
	# col.prop(self, "normalIntensity", slider=True)

	row = self.layout.row()
	col = row.column()
	col.prop(self, "improveUiSettings")
	col = row.column()
	col.prop(self, "combineMaterials")


class MCPREP_OT_prep_materials(bpy.types.Operator, McprepMaterialProps):
	"""Fixes materials and textures on selected objects for Minecraft rendering"""
	bl_idname = "mcprep.prep_materials"
	bl_label = "MCprep Materials"
	bl_options = {'REGISTER', 'UNDO'}

	skipUsage = bpy.props.BoolProperty(
		default=False,
		options={'HIDDEN'})

	def invoke(self, context, event):
		return context.window_manager.invoke_props_dialog(
			self, width=300 * util.ui_scale())

	def draw(self, context):
		draw_mats_common(self, context)

	track_function = "materials"
	track_param = None
	track_exporter = None
	@tracking.report_error
	def execute(self, context):

		# get list of selected objects
		obj_list = context.selected_objects
		if not obj_list:
			if not self.skipUsage:
				self.report({'ERROR'}, "No objects selected")
			return {'CANCELLED'}

		# gets the list of materials (without repetition) from selected
		mat_list = util.materialsFromObj(obj_list)
		if not mat_list:
			if not self.skipUsage:
				self.report({'ERROR'}, "No materials found on selected objects")
			return {'CANCELLED'}

		# check if linked material exists
		engine = context.scene.render.engine
		count = 0
		count_lib_skipped = 0

		for mat in mat_list:
			if not mat:
				conf.log(
					"During prep, found null material:" + str(mat), vv_only=True)
				continue
			elif mat.library:
				count_lib_skipped += 1
				continue

			passes = generate.get_textures(mat)
			if not self.useExtraMaps or self.packFormat == "simple":
				# Clear out extra passes if not needed/requested
				for pass_name in passes:
					if pass_name != "diffuse":
						passes[pass_name] = None
			elif passes.get("diffuse"):
				# Otherwise, attempt to get or load extra passes. Needed if
				# swap texturepack hasn't been used yet, otherwise would need
				# to prep twice (even if the base diff texture was already
				# loaded from that pack).
				diff_filepath = passes["diffuse"].filepath
				# bpy. makes rel to file, os. resolves any os.pardir refs.
				abspath = os.path.abspath(bpy.path.abspath(diff_filepath))
				other_passes = generate.find_additional_passes(abspath)
				for pass_name in other_passes:
					if pass_name not in passes or not passes.get(pass_name):
						# Need to update the according tagged node with tex.
						passes[pass_name] = bpy.data.images.load(
							other_passes[pass_name],
							check_existing=True)

			if self.autoFindMissingTextures:
				for pass_name in passes:
					res = generate.replace_missing_texture(passes[pass_name])
					if res > 0:
						mat["texture_swapped"] = True  # used to apply saturation

			if engine == 'BLENDER_RENDER' or engine == 'BLENDER_GAME':
				res = generate.matprep_internal(
					mat, passes, self.useReflections, self.makeSolid)
				if res == 0:
					count += 1
			elif engine == 'CYCLES' or engine == 'BLENDER_EEVEE':
				res = generate.matprep_cycles(
					mat, passes, self.useReflections,
					self.usePrincipledShader, self.makeSolid, self.packFormat)
				if res == 0:
					count += 1
			else:
				self.report(
					{'ERROR'},
					"Only Blender Internal, Cycles, or Eevee supported")
				return {'CANCELLED'}

			if self.animateTextures:
				sequences.animate_single_material(
					mat, context.scene.render.engine)

		if self.syncMaterials is True:
			bpy.ops.mcprep.sync_materials(
				selected=True, link=False, replace_materials=False, skipUsage=True)
		if self.combineMaterials is True:
			bpy.ops.mcprep.combine_materials(selection_only=True, skipUsage=True)
		if self.improveUiSettings:
			try:
				bpy.ops.mcprep.improve_ui()
			except RuntimeError as err:
				print("Failed to improve UI with error: " + str(err))

		if self.skipUsage is True:
			pass  # Don't report if a meta-call.
		elif count_lib_skipped > 0:
			self.report(
				{"INFO"},
				"Modified {} materials, skipped {} linked ones.".format(
					count, count_lib_skipped))
		elif count > 0:
			self.report({"INFO"}, "Modified " + str(count) + " materials")
		else:
			self.report(
				{"ERROR"},
				"Nothing modified, be sure you selected objects with existing materials!")

		addon_prefs = util.get_user_preferences(context)
		self.track_param = context.scene.render.engine
		self.track_exporter = addon_prefs.MCprep_exporter_type
		return {'FINISHED'}


class MCPREP_OT_materials_help(bpy.types.Operator):
	"""Follow up popup to assist after not getting the expected change"""
	bl_idname = "mcprep.prep_materials_help"
	bl_label = "MCprep Materials Help"
	bl_options = {'REGISTER', 'UNDO'}

	def update_supress_help(self, context):
		"""Update trigger for supressing help popups."""
		if conf.v and self.suppress_help:
			print("Supressing future help popups")
		elif conf.v and not self.suppress_help:
			print("Re-enabling popup warnings")

	help_num = bpy.props.IntProperty(
		default=0,
		options={'HIDDEN'})
	suppress_help = bpy.props.BoolProperty(
		name="Don't show this again",
		default=False,
		options={'HIDDEN'},
		update=update_supress_help)

	def invoke(self, context, event):
		# check here whether to trigger popup, based on supression
		return context.window_manager.invoke_props_dialog(
			self, width=400 * util.ui_scale())

	def draw(self, context):
		layout = self.layout
		col = layout.column()
		if self.help_num == 0:
			# No specific error occured
			col.scale_y = 0.7
			col.label(text="No specific MCprep material issue identified.")
			col.label(text="Still need help? Press OK below to open an issue.")
		elif self.help_num == 1:
			# No materials modified, because no materials detected
			col.scale_y = 0.7
			col.label(text="Could not prep materials because")
			col.label(text="because none of the selected objects")
			col.label(text="have materials. Be sure to select the")
			col.label(text="model or world import before prepping!")
		elif self.help_num == 2:
			# Missing SOME textures detected, either because find msising is off
			# or if replacement still not found even with setting on
			col.scale_y = 0.7
			col.label(text="Some materials have missing textures,")
			col.label(text="these may show up as pink or black materials")
			col.label(text="in the viewport or in a render. Try using:")
			col.label(text="file > External Data > Find missing files")
		elif self.help_num == 3:
			# It worked, but maybe the user isn't seeing what they expect
			col.scale_y = 0.7
			col.label(text="Material prepping worked, but you might need")
			col.label(text="to \"Improve UI\" or go into texture/rendered")
			col.label(text="mode (shift+z) to see imrpoved textures")

		col.prop(self, "suppress_help")
		self.help_num = 0  # reset in event of unset re-trigger

	def execute(self, context):
		if self.help_num == 0:
			bpy.ops.wm.url_open(url="")

		return {'FINISHED'}


class MCPREP_OT_swap_texture_pack(
	bpy.types.Operator, ImportHelper, McprepMaterialProps):
	"""Swap current textures for that of a texture pack folder"""
	bl_idname = "mcprep.swap_texture_pack"
	bl_label = "Swap Texture Pack"
	bl_description = (
		"Change the texture pack for all materials of selected objects, "
		"select a folder path for an unzipped resource pack or texture folder")
	bl_options = {'REGISTER', 'UNDO'}

	filter_glob = bpy.props.StringProperty(
		default="",
		options={'HIDDEN'})
	use_filter_folder = True
	fileselectparams = "use_filter_blender"
	filepath = bpy.props.StringProperty(subtype='DIR_PATH')
	filter_image = bpy.props.BoolProperty(
		default=True,
		options={'HIDDEN', 'SKIP_SAVE'})
	filter_folder = bpy.props.BoolProperty(
		default=True,
		options={'HIDDEN', 'SKIP_SAVE'})
	prepMaterials = bpy.props.BoolProperty(
		name="Prep materials",
		description="Runs prep materials after texture swap to regenerate materials",
		default=False)
	skipUsage = bpy.props.BoolProperty(
		default=False,
		options={'HIDDEN'})

	@classmethod
	def poll(cls, context):
		addon_prefs = util.get_user_preferences(context)
		return addon_prefs.MCprep_exporter_type != "(choose)"

	def draw(self, context):
		row = self.layout.row()
		col = row.column()
		subcol = col.column()
		subcol.scale_y = 0.7
		subcol.label(text="Select any subfolder of an")
		subcol.label(text="unzipped texture pack, then")
		subcol.label(text="press 'Swap Texture Pack'")
		subcol.label(text="after confirming these")
		subcol.label(text="settings below:")
		col.prop(self, "useExtraMaps")
		col.prop(self, "animateTextures")
		col.prop(self, "prepMaterials")
		if self.prepMaterials:
			col.prop(self, "packFormat")
			col.prop(self, "usePrincipledShader")
			col.prop(self, "useReflections")
			col.prop(self, "autoFindMissingTextures")
			col.prop(self, "syncMaterials")
			col.prop(self, "improveUiSettings")
			col.prop(self, "combineMaterials")

	track_function = "texture_pack"
	track_param = None
	track_exporter = None
	@tracking.report_error
	def execute(self, context):
		addon_prefs = util.get_user_preferences(context)

		# check folder exist, but keep relative if relevant
		folder = self.filepath
		if os.path.isfile(bpy.path.abspath(folder)):
			folder = os.path.dirname(folder)
		conf.log("Folder: " + folder)

		if not os.path.isdir(bpy.path.abspath(folder)):
			self.report({'ERROR'}, "Selected folder does not exist")
			return {'CANCELLED'}

		# get list of selected objects
		obj_list = context.selected_objects
		if len(obj_list) == 0:
			self.report({'ERROR'}, "No objects selected")
			return {'CANCELLED'}

		# gets the list of materials (without repetition) from selected
		mat_list = util.materialsFromObj(obj_list)
		if len(obj_list) == 0:
			self.report({'ERROR'}, "No materials found on selected objects")
			return {'CANCELLED'}
		_ = generate.detect_form(mat_list)
		invalid_uv, affected_objs = uv_tools.detect_invalid_uvs_from_objs(obj_list)

		self.track_exporter = addon_prefs.MCprep_exporter_type

		# set the scene's folder for the texturepack being swapped
		context.scene.mcprep_texturepack_path = folder

		conf.log("Materials detected: " + str(len(mat_list)))
		res = 0
		for mat in mat_list:
			self.preprocess_material(mat)
			res += generate.set_texture_pack(mat, folder, self.useExtraMaps)
			if self.animateTextures:
				sequences.animate_single_material(
					mat, context.scene.render.engine)
			# may be a double call if was animated tex
			generate.set_saturation_material(mat)

		if self.prepMaterials:
			bpy.ops.mcprep.prep_materials(
				animateTextures=self.animateTextures,
				autoFindMissingTextures=self.autoFindMissingTextures,
				combineMaterials=self.combineMaterials,
				improveUiSettings=self.improveUiSettings,
				usePrincipledShader=self.usePrincipledShader,
				useReflections=self.useReflections,
				useExtraMaps=self.useExtraMaps,
				normalIntensity=self.normalIntensity,
				makeSolid=self.makeSolid,
				syncMaterials=self.syncMaterials,
				packFormat=self.packFormat,
				skipUsage=True)

		if invalid_uv:
			self.report({'ERROR'}, (
				"Detected scaled UV's (all in one texture), be sure to use "
				"Mineway's 'Export Tiles for textures'"))
			conf.log("Detected scaledd UV's, incompatible with swap textures")
			conf.log([ob.name for ob in affected_objs], vv_only=True)
		else:
			self.report({'INFO'}, "{} materials affected".format(res))
		self.track_param = context.scene.render.engine
		return {'FINISHED'}

	def preprocess_material(self, material):
		"""Preprocess materials for special edge cases"""

		# in texture packs, this is actually just a transparent overaly -
		# but in Mineways export, this is the flattened grass/drit block side
		if material.name == "grass_block_side_overlay":
			material.name = "grass_block_side"
			conf.log("Renamed material: grass_block_side_overlay to grass_block_side")


class MCPREP_OT_load_material(bpy.types.Operator, McprepMaterialProps):
	"""Load the select material from the active resource pack and prep it"""
	bl_idname = "mcprep.load_material"
	bl_label = "Generate material"
	bl_description = (
		"Generate and apply the selected material based on active resource pack")
	bl_options = {'REGISTER', 'UNDO'}

	skipUsage = bpy.props.BoolProperty(default=False, options={'HIDDEN'})

	@classmethod
	def poll(cls, context):
		return context.object and context.scene.mcprep_props.material_list

	def invoke(self, context, event):
		return context.window_manager.invoke_props_dialog(
			self, width=300 * util.ui_scale())

	def draw(self, context):
		draw_mats_common(self, context)

	track_function = "generate_mat"
	track_param = None
	@tracking.report_error
	def execute(self, context):
		scn_props = context.scene.mcprep_props
		mat_item = scn_props.material_list[scn_props.material_list_index]
		mat, err = self.generate_base_material(
			context, mat_item.name, mat_item.path)
		if mat is None and err:
			self.report({"ERROR"}, err)
			return {'CANCELLED'}
		elif mat is None:
			self.report({"ERROR"}, "Failed generate base material")
			return {'CANCELLED'}

		if not context.object.material_slots:
			context.object.data.materials.append(mat)  # Auto-creates slot.
		else:
			mat_ind = context.object.active_material_index
			context.object.material_slots[mat_ind].material = mat
		# Using the above in place of below due to some errors of:
		# "attribute "active_material" from "Object" is read-only"
		# context.object.active_material = mat

		# Don't want to generally run prep, as this would affect everything
		# selected, as opposed to affecting just the new material
		# bpy.ops.mcprep.prep_materials()
		# Instead, run the update steps below copied from the MCprep inner loop
		res, err = self.update_material(context, mat)
		if res is False and err:
			self.report({"ERROR"}, err)
			return {'CANCELLED'}
		elif res is False:
			self.report({"ERROR"}, "Failed to prep generated material")
			return {'CANCELLED'}

		self.track_param = context.scene.render.engine
		return {'FINISHED'}

	def generate_base_material(self, context, name, path):
		"""Generate a base material from name and active resource pack"""
		image = bpy.data.images.load(path, check_existing=True)
		mat = bpy.data.materials.new(name=name)

		engine = context.scene.render.engine
		if engine == 'BLENDER_RENDER' or engine == 'BLENDER_GAME':
			generate.set_internal_texture(image, mat, self.useExtraMaps)
		elif engine == 'CYCLES' or engine == 'BLENDER_EEVEE':
			# need to create at least one texture node first, then the rest works
			mat.use_nodes = True
			node_diff = mat.node_tree.nodes.new('ShaderNodeTexImage')
			node_diff.image = image
			node_diff["MCPREP_diffuse"] = True

			# Initialize extra passes as well
			node_spec = mat.node_tree.nodes.new('ShaderNodeTexImage')
			node_spec["MCPREP_specular"] = True
			node_nrm = mat.node_tree.nodes.new('ShaderNodeTexImage')
			node_nrm["MCPREP_normal"] = True

			conf.log("Added blank texture node")

			# now use standard method to update textures
			generate.set_cycles_texture(image, mat, self.useExtraMaps)
		else:
			return None, "Only Blender Internal, Cycles, or Eevee supported"

		return mat, None

	def update_material(self, context, mat):
		"""Update the initially created material"""
		if not mat:
			conf.log("During prep, found null material:" + str(mat), vv_only=True)
			return
		elif mat.library:
			return

		engine = context.scene.render.engine
		passes = generate.get_textures(mat)
		conf.log("Load Mat Passes:" + str(passes), vv_only=True)
		if not self.useExtraMaps:
			for pass_name in passes:
				if pass_name != "diffuse":
					passes[pass_name] = None

		if self.autoFindMissingTextures:
			for pass_name in passes:
				res = generate.replace_missing_texture(passes[pass_name])
				if res > 0:
					mat["texture_swapped"] = True  # used to apply saturation

		if engine == 'BLENDER_RENDER' or engine == 'BLENDER_GAME':
			res = generate.matprep_internal(
				mat, passes, self.useReflections, self.makeSolid)
		elif engine == 'CYCLES' or engine == 'BLENDER_EEVEE':
			res = generate.matprep_cycles(
				mat, passes, self.useReflections,
				self.usePrincipledShader, self.makeSolid, self.packFormat)
		else:
			return False, "Only Blender Internal, Cycles, or Eevee supported"

		success = res == 0

		if self.animateTextures:
			sequences.animate_single_material(
				mat, context.scene.render.engine)

		return success, None


# -----------------------------------------------------------------------------
# Registration
# -----------------------------------------------------------------------------


classes = (
	MCPREP_OT_prep_materials,
	MCPREP_OT_materials_help,
	MCPREP_OT_swap_texture_pack,
	MCPREP_OT_load_material,
)


def register():
	util.make_annotations(McprepMaterialProps)
	for cls in classes:
		util.make_annotations(cls)
		bpy.utils.register_class(cls)


def unregister():
	for cls in reversed(classes):
		bpy.utils.unregister_class(cls)
